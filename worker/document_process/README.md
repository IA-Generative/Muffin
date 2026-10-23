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
   au backend (`ChunkCreate.embedding`). `llm`, la stratégie par défaut, est faite par fenêtres de pages
   (`chunking_window_pages`) : le modèle de découpage de la collection reçoit les paragraphes numérotés
   et répond par les numéros de ceux qui commencent un chunk. Il ne réécrit jamais le texte. Une
   fenêtre où il échoue, ou une collection sans modèle, est découpée par paragraphe.
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

## Logs des tâches (#305)

Tout passe par loguru (`app/task_logging.py`, le même module dans chaque worker) :

- Le `logging` standard (Celery, le beat, les bibliothèques) est redirigé vers loguru. Celery ne
  configure plus le logging lui-même (signal `setup_logging`).
- `task_prerun` place la tâche en cours dans une variable de contexte, propre à chaque thread : en
  pool de threads, chaque tâche ne prend que ses propres lignes. Chaque ligne émise pendant la tâche
  porte `celery_task_id`, `task_name`, et le `document_id` / `collection_id` de ses arguments. Elles
  apparaissent sur stdout (`LOG_FORMAT=json` pour du JSON) et sont envoyées au backend.
- L'envoi se fait par lot, à partir de `TASK_LOG_LEVEL` (INFO par défaut) : toutes les 2 s pendant
  la tâche, puis à sa fin (`POST /internal/task-logs`, table `task_log_entries`). Si le backend est
  injoignable, la tâche n'échoue pas : les lignes partent avec le lot suivant.
- Lecture : `GET /api/tasks/{id}/logs?after=&level=` pour une tâche, et
  `GET /api/collections/{cid}/documents/{did}/logs` pour toute la pipeline d'un document. Le front
  les suit en direct.
- Le beat purge chaque heure les lignes plus vieilles que `TASK_LOG_RETENTION_DAYS` (backend,
  7 jours).

## Révocation d'une tâche

Révoquer une tâche (bouton « Révoquer », annulation d'un run) l'arrête pour de bon, quelle que soit sa
situation. Celery seul ne suffit pas : son `revoke` est une diffusion aux workers présents à cet
instant, gardée en mémoire, et un kill que seul un pool prefork sait faire.

- Le backend (`revoke_tasks`) laisse un drapeau dans Redis (`muffin:revoked:<id>`), écrit l'état
  `REVOKED` dans le backend de résultats, et diffuse le `revoke` (avec `terminate`). La révocation d'une
  tâche s'étend à toutes celles qu'elle a lancées encore actives, et un document en cours de traitement
  passe en erreur « Traitement annulé. ».
- Chaque worker (`app/task_revocation.py`, la même classe `RevocableTask` dans les quatre) regarde ce
  drapeau au démarrage de chaque tâche et l'abandonne s'il est posé. C'est ce qui arrête une tâche qui
  attendait dans la queue quand un pod démarre (déploiement, KEDA), ou qui est redistribuée par Redis
  après la mort de son worker.
- Le pod d'enrichissement tourne en threads, où Celery ne peut pas tuer une tâche : `raise_if_revoked`
  est appelé avant chaque appel LLM et chaque embedding, et une tâche révoquée s'y arrête (`TaskRevoked`,
  un `Ignore` : ce n'est pas un échec du document).

Si un worker tombe en pleine tâche, la tâche reste « en cours » : avec `acks_late`, Redis la redistribue
à un autre worker une fois `BROKER_VISIBILITY_TIMEOUT_SECONDS` passé (4 h), puis dans les ~100 s qui
suivent. Avant cela, la révoquer la fait passer à « révoquée » tout de suite, et elle ne sera pas rejouée.

## Extraction d'un long PDF (#331)

Un PDF de plus de `PARSE_RANGE_PAGES` pages (25) n'est pas parsé d'un bloc. `process_document` compte ses
pages, annonce les plages comme les morceaux attendus du stage `extraction` (`document_stages`) et lance
les `PARSE_WINDOW` (4) premières tâches `parse_page_range`. Chacune parse sa plage (`target_pages`), écrit
ses pages, marque son morceau fait - le backend répond où en est le stage, de façon atomique (ligne
verrouillée) - et logge l'avancement avec une estimation du temps restant. Elle lance ensuite la plage
suivante de sa fenêtre : la file ne contient jamais plus de `PARSE_WINDOW` plages du document. La plage qui
complète le stage (`completed_now`, vrai pour une seule) lance le chunking. Une plage en échec met le
document en erreur et arrête la fenêtre ; une tâche révoquée ne lance pas la suivante. Les autres formats
(Office, images) et les PDF courts restent une seule tâche.

## Lecture d'une grosse archive ZIP par lots (#334)

`import_zip` ne parcourt plus les fichiers de l'archive. Il la lit **par plages d'octets** (`storage.open_seekable`,
sans la télécharger : ni lui, ni chaque lot), applique les règles de sécurité, crée les sous-collections, range
le plan (quels fichiers, dans quelle collection) dans `<archive>.plan.json` puis le découpe en lots de
`IMPORT_BATCH_FILES` (50) fichiers, annoncés au backend comme les morceaux de l'import. `IMPORT_WINDOW` (4)
tâches `import_zip_batch` partent ; chacune lit son lot (extraction, hash, doublon, envoi, enregistrement),
dit au backend où elle en est (`batches/{key}/done`, ligne verrouillée) et lance le lot suivant de sa fenêtre.
Le lot qui complète l'import (`completed_now`, un seul) rend compte, avec le résumé de tous, comme le ferait
une tâche unique. Une archive d'un seul lot est lue par `import_zip` lui-même.

- **Taille totale** (`ZIP_IMPORT_MAX_TOTAL_BYTES`) : garantie par le plan (somme des tailles déclarées, que
  zipfile ne lit jamais au-delà), donc plus décomptée fichier par fichier ; la limite par fichier reste
  contrôlée à la lecture.
- **Doublons** : le test avant envoi reste, mais deux lots peuvent lire le même fichier en même temps ; le
  backend tranche à l'enregistrement (verrou par collection et hash) : le perdant est retiré du stockage et
  listé comme doublon.
- **Échec** : un lot en échec met l'import en `failed` avec ce que les autres avaient rendu compte et ce
  qu'il avait fait lui-même ; les lots déjà lancés finissent, aucun autre n'est lancé. Un lot rejoué compte
  une fois, tel qu'il s'était d'abord rendu compte.
- Les tâches de lot ne sont pas listées dans les tâches de l'utilisateur ; leurs logs le sont, rangés sous la
  collection racine de l'import.

## Fenêtre d'extraction d'un import ZIP (#335)

Les documents d'un import ZIP ne sont pas tous mis en file à leur enregistrement : le backend les garde
« en attente » (`import_documents`) et n'en libère que `IMPORT_PROCESSING_WINDOW` (4) à la fois, toujours
avec la priorité basse d'un import. Quand l'extraction d'un document se termine (le worker appelle
`extraction-done` là où il lance le chunking - donc aussi quand la dernière plage d'un long PDF complète
l'extraction), ou qu'il passe en erreur, est annulé ou supprimé, sa place va au document suivant de son
import. Une tâche `release_import_queue`, envoyée par le beat toutes les 5 minutes, libère ce que ces
appels n'ont pas fait (appel perdu) ; un document libéré mais jamais extrait cesse de compter au bout de
`IMPORT_SLOT_TIMEOUT_SECONDS`.

## Texte positionné des pages (#350)

Avec chaque page, le worker envoie ses **lignes et ses mots**, avec leur boîte **normalisée entre 0 et 1** par la
taille de la page (elle tombe donc sur la capture quelle que soit l'échelle à laquelle elle est rendue) et leur
intervalle de caractères dans le texte de la page (`app/text_boxes.py`, `build_text_boxes`). liteparse les donne
(`text_items`, et `words` avec `emit_word_boxes`, activé dans `app/parsing.py`) ; le backend les range dans
`page_text_boxes`, remplacées avec la page. L'intervalle vaut `None` quand la ligne n'est pas retrouvée dans le texte
(OCR) : elle se lit, elle ne se place pas. Les plages d'un long PDF (#331) les envoient comme le reste de leurs pages.
L'empreinte de l'extraction (#300) en tient compte (`layout`) : un fichier n'est pas réutilisé depuis une extraction
faite avant, qui n'a pas ces données. Les documents déjà indexés n'en ont pas ; la relance de l'indexation (#340) les
leur donne.

Côté backend, `POST /collections/{id}/documents/{id}/pages/{n}/highlights` (un POST, car un chunk cité est trop long
pour une adresse) dit où est un passage : les intervalles de caractères à surligner et les rectangles à encadrer.

## Entités : où elles sont dans le texte (#352)

`extract_entities_window` demande toujours au LLM le nom et le type des entités d'une fenêtre de pages, mais le worker
**retrouve ensuite chaque nom dans le texte de la fenêtre** (`app/entity_mentions.py` : les mots dans l'ordre, séparés
par n'importe quel blanc, sans tenir compte de la casse, et comme mots entiers - « Paris » n'est pas dans « Parisien »)
et envoie ses occurrences (page, intervalle de caractères, au plus 10 par page et par entité). Le backend les range dans
`entity_mentions`, remplacées avec la fenêtre (#299), copiées par la réutilisation (#300) et retirées avec le document.
Le nombre de mentions est **le nombre d'occurrences retrouvées** ; une entité que le modèle a normalisée ou traduite et
qui n'est nulle part dans le texte garde le nombre de fois où il l'a listée, sans occurrence (`occurrences: 0` dans
l'API : listée, rien à montrer). Les relations portent la **phrase qui les justifie** : le modèle la donne
(`evidence`), le worker ne la garde que si elle est mot pour mot dans le texte de la fenêtre (comme la preuve d'une
paire question-réponse) avec sa page et sa place ; sinon la relation reste, sans phrase. L'empreinte des entités (#300)
en tient compte (`positions`).

Côté API : `GET /collections/{id}/entities/{entity_id}/mentions[?document_id=]` rend les occurrences dans l'ordre de
lecture (document, page, place) ; `entities` donne `occurrences`, `relations` donne `source`. L'interface ouvre une
entité sur ses occurrences (« Occurrence 2 sur 7 »), nom surligné et encadré à sa place.

## Position des chunks dans les pages (#353)

Chaque chunk garde où il est : `extras["spans"] = [{"page": 3, "start": 120, "end": 560}, …]`, un **intervalle de
caractères par page touchée**, dans le contenu de cette page (`app/chunking.py`, `_spans` et `_chunk_of` ; `strip()`
est pris en compte, l'intervalle commence au premier caractère du chunk). Des intervalles et non des rectangles : les
rectangles se déduisent de `page_text_boxes` (#350) à la lecture. `fixed` et `paragraphs` ont les bornes de leur
découpage ; `llm` fusionne les intervalles de ses paragraphes consécutifs (un par page) ; `semantic` ne donne plus à
chaque chunk les pages de sa fenêtre mais les siennes (`page_start`/`page_end` sont la première et la dernière page de
ses intervalles). L'empreinte des chunks (#300) en tient compte (`positions`) : un fichier n'est pas réutilisé depuis un
découpage fait avant, qui n'a ni intervalles ni ces pages. Les chunks d'avant n'ont pas `spans` : la route
`POST …/pages/{n}/highlights` accepte un `chunk_id` - exact avec les intervalles, par recherche du texte du chunk sans -
et dit les pages du chunk (`pages`), que la modale de source parcourt.

## Source d'une paire question-réponse (#351)

Une paire générée garde sa page (`source_page`), son passage (`source_excerpt`, aplati) et **où il est** dans le texte
brut de cette page : `source_start` / `source_end` (`evidence_position` dans `app/tasks/qa.py`, recherche tolérante - casse
et espaces ignorés - qui trouve la même preuve que la vérification de `locate_evidence`, la première occurrence si le
passage est deux fois dans la page). Le backend les rend avec la paire (`GET …/qa-pairs`) et avec un résultat de
recherche (`/api/internal/qa-search`, `source` : document, page, passage, intervalle), la réutilisation (#300) les
recopie, et l'agent les porte jusqu'à la citation (`qa_source`). L'interface ouvre alors la source sur sa page, passage
surligné et encadré à l'endroit exact ; une paire d'avant, ou dont la position n'a pas été trouvée, retombe sur la
recherche du passage par son texte.

## Limites de temps (#294)

Aucune tâche n'est tuée parce qu'elle est grosse : il n'y a plus de limite dure (l'ancienne,
`task_time_limit=300`, tuait un gros OCR ou un import ZIP en plein milieu, le laissant « en cours »).
Ce qui peut bloquer est borné là où ça se passe :

- **OCR** : le parseur tourne dans un processus à lui, avec un délai (`OCR_PARSE_TIMEOUT_SECONDS`) - par
  plage de pages pour un long PDF (voir ci-dessous). Passé ce délai, il est tué et remplacé, et la tâche échoue proprement : le document passe en erreur.
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
