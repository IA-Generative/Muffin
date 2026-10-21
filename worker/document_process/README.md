# worker/document_process

Worker Celery qui ingère un document (fichier uploadé ou URL scrapée) dans une collection :
parsing, OCR si besoin, chunking, résumé, tags, génération de paires QA, extraction
entités/relations, et calcul des embeddings - jusqu'à ce que le document soit cherchable par
l'agent de recherche.

Ne parle jamais directement à Postgres/Meilisearch : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`.

## Pipeline

Une chaîne de tâches Celery, chacune enchaînant la suivante (voir `app/tasks.py`) :

1. `process_document` - point d'entrée : parse le fichier (`app/parsing.py`, liteparse + OCR
   Tesseract pour les pages scannées) ou scrape l'URL (`app/scraping.py`), extrait le texte
   page par page.
2. `chunk_document` - découpe le texte en chunks selon la stratégie de la collection
   (`app/chunking.py` : `paragraph`/`fixed`/`semantic`/`llm`), calcule leur embedding, les envoie
   au backend (`ChunkCreate.embedding`).
3. En parallèle, par fenêtres de pages (`app/windows.py`) :
   - `summarize_document` - résumé du document, embeddé lui aussi pour la recherche par résumé.
   - `tag_document` - tags automatiques.
   - `generate_qa_window` - paires question/réponse générées et embeddées (cache QA de l'agent).
   - `extract_entities_window` - entités et relations mentionnées dans le document.
4. `update_collection_description` - met à jour la description globale de la collection une fois
   tous ses documents traités.

Chaque tâche est fail-soft sur l'embedding (une erreur de calcul d'embedding n'empêche jamais le
chunk/résumé/QA d'être persisté, juste de ne pas être trouvable par recherche vectorielle - voir
`docs/environment-variables.md` à la racine du repo, section LLM hub).

## Structure

```
app/
  tasks.py          les tâches Celery elles-mêmes, chaînées via _spawn
  celery_app.py     app Celery (queue, nom des tâches - doit matcher backend/app/core/tasks.py)
  parsing.py        extraction de texte depuis un fichier (+ OCR)
  scraping.py       extraction de texte depuis une URL
  chunking.py       stratégies de découpage en chunks
  windows.py        découpage d'un document en fenêtres de pages pour le traitement par lots
  storage.py        upload vers RustFS (fichier original, screenshots de page)
  backend_client.py client HTTP vers les endpoints /internal/* du backend
  config.py         Settings (voir docs/environment-variables.md)
```

## Développer

```bash
cd worker/document_process
uv sync
uv run pytest -q               # tests
uv run ruff check . && uv run ruff format --check .
```

## Pods et queues (#291)

Une seule image, trois pods, chacun sur ses queues (routage par nom de tâche dans
`app/celery_app.py`) :

| Pod (compose / Helm) | Queues | Pool | Tâches |
|---|---|---|---|
| `worker-document-process` / `document_process` | `document_extraction` (+ `document_processing`, l'ancienne queue, pendant une release) | prefork | `process_document`, `process_tabular_document`, `refresh_url_document`, `scan_url_refresh` - et le beat (`-B`) |
| `worker-document-enrichment` / `document_enrichment` | `document_enrichment` | threads (`-c 16`) | `chunk_document` (embeddings), `summarize_document`, `generate_qa_window`, `extract_entities_window`, `tag_document`, `update_collection_*`, `rollup_collection_description`, `generate_collection_qa` |
| `worker-index-rebuild` / `index_rebuild` | `index_rebuild`, `document_import` | prefork (`-c 2`) | `rebuild_index`, `import_zip` |

- L'extraction (OCR) est limitée par le CPU ; l'enrichissement attend surtout l'API d'embeddings/LLM,
  d'où un pool de threads ; un import ZIP ou une reconstruction d'index sont de longues
  entrées/sorties qui ne doivent bloquer ni l'un ni l'autre.
- Les documents créés par un import ZIP sont envoyés dans `document_extraction` avec la priorité la
  plus basse (`BULK_PRIORITY` côté backend) : Redis les garde dans une liste à part, que le worker ne
  lit qu'une fois la liste normale vide. Un fichier déposé à la main passe donc avant les 2 000
  documents d'une archive.
- La commande par défaut de l'image (`Dockerfile`) est celle du pod d'extraction ; les deux autres la
  remplacent.
- Les logs d'une tâche (`capture_task_logs`) ne prennent que les lignes de son propre thread : sans
  ça, en pool de threads, chaque tâche récupérerait aussi celles des autres.

## Limites de temps (#294)

Aucune tâche n'est tuée parce qu'elle est grosse : il n'y a plus de limite dure (l'ancienne,
`task_time_limit=300`, tuait un gros OCR ou un import ZIP en plein milieu, le laissant « en cours »).
Ce qui peut bloquer est borné là où ça se passe :

- **OCR** : le parseur tourne dans un processus à lui, avec un délai (`OCR_PARSE_TIMEOUT_SECONDS`). Passé
  ce délai, il est tué et remplacé, et la tâche échoue proprement : le document passe en erreur.
- **Appels backend, S3, URL** : délais explicites (client backend 60 s, S3 10 s / 60 s, URL 120 s).
- **Toute tâche** : une limite *souple* (`TASK_SOFT_TIME_LIMIT_SECONDS`), filet de sécurité large - une
  exception levée dans la tâche, qui échoue et rend compte. Seuls les pods en prefork l'appliquent.
- **Import ZIP** : au-delà de `IMPORT_SOFT_TIME_LIMIT_SECONDS`, l'import se termine en `failed`, avec le
  résumé de ce qui a été créé.
- **Reconstruction d'index** : reprenable, elle tourne par tranches (`REBUILD_SLICE_SECONDS`) : à la fin
  d'une, une nouvelle tâche continue là où la base en est. Au-delà de `REBUILD_MAX_SLICES` tranches, elle
  échoue.
- **`BROKER_VISIBILITY_TIMEOUT_SECONDS`** doit dépasser toutes ces limites : les tâches sont acquittées
  à leur fin (`acks_late`) et, passé ce délai, Redis en donnerait une qui tourne encore à un second
  worker. C'est aussi le temps de reprise d'une tâche dont le worker est mort.

## Rejeu d'une tâche (#299)

Une tâche peut s'exécuter deux fois (Redis la rejoue après la mort d'un pod). Le pipeline écrit donc
de façon à ce qu'un rejeu laisse le même état qu'une seule exécution :

- **Pages et chunks** : upsert sur `(document, numéro de page)` et `(document, position)` (contraintes
  d'unicité). Un chunk garde son id, donc son vecteur Meilisearch, d'une exécution à l'autre. Après
  l'écriture, `prune_pages` / `prune_chunks` retirent ce qu'une exécution plus longue avait laissé
  après le dernier.
- **QA, entités, relations** : le modèle reformule à chaque exécution, il n'y a donc pas de clé
  naturelle. Chaque *fenêtre de pages* (`window:3-4`, `pages:3-6`), le profil tabulaire (`tabular`) et
  les paires d'une description de collection (`collection:<hash>`) forment une exécution qui **remplace**
  la précédente de même clé, en un seul appel atomique (`replace_generated_qa`,
  `replace_entity_window`). Les compteurs de mentions sont corrigés de la contribution précédente de la
  fenêtre au lieu d'être incrémentés. Une paire validée par une personne n'est jamais remplacée.
- Résumé et tags sont déjà écrits par remplacement.

Ce qui a été dérivé d'un document disparaît avec lui, côté backend : à sa suppression (paires générées,
même validées, entités qu'il était seul à mentionner, relations) et à un reprocess (sauf les paires
validées).

## Réutilisation des résultats d'un même fichier (#300)

Un même fichier, ajouté deux fois (dans la même collection, ou dans deux collections), n'est pas
retraité en entier : ce que le pipeline a déjà calculé pour ces octets est repris, ce qui évite l'OCR,
les embeddings et les appels LLM, la partie coûteuse.

Chaque document a un `content_hash` : le SHA-256 de ses octets (pour une page HTML servie par une URL,
celui de son texte normalisé, car ses octets changent à chaque lecture). Il est calculé par le backend à
l'upload, par le worker pendant la lecture d'un membre de ZIP, et par `process_document` pour un fichier
qui n'en a pas encore (fichier remplacé, ajouté avant cette fonctionnalité).

Le pipeline compte six **étapes**, réutilisées chacune de son côté (`app/reuse.py`) : `extraction` (pages
et captures), `chunks` (chunks et vecteurs), `summary`, `qa`, `entities`, `tags`. Avant de calculer une
étape, le worker donne au backend son **empreinte** : le hash du fichier et ce dont l'étape dépend, rien
de plus (la langue OCR et la version du parseur ; pour le résumé, le modèle réellement utilisé -
`get_default_chat_model` quand aucun n'est configuré -, les instructions de l'étape et ses fenêtres ; les
tags dépendent aussi du résumé). L'embedding du résumé, des QA et des entités n'en fait pas partie : leur
texte est repris et le backend refait le vecteur si le modèle d'embedding diffère. Les chunks, eux,
dépendent du modèle d'embedding.

Si un autre document du même fichier, dans n'importe quelle collection, a **terminé** l'étape sous la
même empreinte, le backend en copie les résultats (`result_reuse.py` : les captures sont copiées côté
RustFS, les vecteurs relus dans l'index source et réécrits dans celui du document, avec de nouveaux ids)
et le worker passe à la suite sans rien calculer. Sinon il calcule, puis déclare l'étape terminée, ce qui
en fait une source pour le suivant. Une étape faite par fenêtres de pages (QA, entités) annonce ses
fenêtres et est terminée quand chacune est écrite (le backend le note à chaque remplacement de fenêtre,
#299).

- Une copie est **indépendante** : supprimer le document source ne lui retire rien.
- Seules les paires QA **générées et non validées** sont copiées : une validation, ou une paire écrite à la
  main, est le travail d'une personne dans sa collection.
- Aucune information sur la source n'est exposée par l'API : c'est interne au backend.
- Un échec de la copie (Meilisearch, S3) laisse le document intact et l'étape est simplement calculée : la
  réutilisation est une optimisation, jamais un point de défaillance.
- Un document reprocessé, déplacé ou supprimé n'est plus une source (ses étapes sont effacées avec ce qu'il
  avait dérivé).
- Changer la façon dont une étape calcule son résultat (le découpage, un prompt) demande d'incrémenter
  `FINGERPRINT_VERSION`, sinon les documents indexés avec l'ancien code seraient repris.

Les fichiers tabulaires (CSV, XLSX...) ont un hash et la détection de doublon, mais pas encore la
réutilisation : leur pipeline (profil DuckDB, résumé et QA tirés du profil) est à part.

## Reconstruction blue/green de l'index (#12)

La tâche `app.tasks.rebuild_index` (`app/tasks/rebuild.py`) reconstruit l'index de recherche d'une
collection avec un nouveau modèle d'embedding, pendant que l'index actuel continue de répondre. Elle
ne garde aucun état : à chaque tour elle demande au backend ce qu'il manque au nouvel index (comparé à
PostgreSQL, source de vérité), calcule les vecteurs par lots, les renvoie, puis demande la bascule
atomique quand il ne manque plus rien. Un job tué ou redélivré reprend donc là où en est la base.

Elle tourne sur sa propre queue, `index_rebuild` (`REBUILD_QUEUE_NAME`), servie par le pod
`index_rebuild` (voir plus haut) : une grosse reconstruction ne retarde pas l'ingestion.
