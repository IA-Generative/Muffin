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

Le worker tourne dans `docker-compose.yaml` sous le service `worker-document-process`, sur la
queue Celery `document_processing`.
