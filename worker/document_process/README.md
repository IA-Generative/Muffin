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

## Reconstruction blue/green de l'index (#12)

La tâche `app.tasks.rebuild_index` (`app/tasks/rebuild.py`) reconstruit l'index de recherche d'une
collection avec un nouveau modèle d'embedding, pendant que l'index actuel continue de répondre. Elle
ne garde aucun état : à chaque tour elle demande au backend ce qu'il manque au nouvel index (comparé à
PostgreSQL, source de vérité), calcule les vecteurs par lots, les renvoie, puis demande la bascule
atomique quand il ne manque plus rien. Un job tué ou redélivré reprend donc là où en est la base.

Elle tourne sur sa propre queue, `index_rebuild` (`REBUILD_QUEUE_NAME`), servie par le pod
`index_rebuild` (voir plus haut) : une grosse reconstruction ne retarde pas l'ingestion.
