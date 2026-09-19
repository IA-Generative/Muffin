# worker/evaluation

Worker Celery qui exécute un run d'évaluation retrieval pour une collection (voir issue #11) :
rejoue chaque paire QA - validée ou pas - à travers la même recherche que l'agent, note la
pertinence des résultats, génère une réponse, puis envoie un `EvaluationRun` complet au backend.

Ne parle jamais directement à Postgres/Meilisearch : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`.

Dans sa propre queue Celery (`evaluation`), séparée de `document_processing` et
`agent_execution` : un run d'évaluation itère sur toutes les paires QA d'une collection, refait une
recherche + une génération pour chacune - potentiellement long et gourmand en appels LLM, ça ne
doit jamais faire attendre une vraie requête utilisateur ni retarder l'ingestion de documents.

## Ce que fait `run_evaluation` (`app/tasks.py`)

1. Récupère les paramètres de la collection (chunking/embedding, modèle configuré pour
   l'étape `evaluation` si défini, sinon le modèle de chat par défaut du hub LLM).
2. Récupère **toutes** les paires QA de la collection, validées ou pas. Une paire sans document
   source (`document_id`) est ignorée : la pertinence ne peut être jugée qu'au niveau document
   (une `QaPair` n'a pas de vérité terrain au niveau chunk - voir `app/models/qa.py` côté
   backend), donc une paire sans document n'a rien contre quoi noter le retrieval.
3. Pour chaque paire évaluable : recherche les `k` chunks les mieux classés (même endpoint
   `/internal/search` que l'agent), calcule precision@k/recall@k/MRR/nDCG (`app/metrics.py`) en
   comparant les documents retrouvés au document source de la paire, puis génère une réponse à
   partir des extraits retrouvés.
4. Poste un unique `EvaluationRun` complet au backend - le modèle n'a pas d'état "en cours" (pas
   de colonne `status`), donc rien n'est créé avant que tout soit calculé. Les métriques sont
   agrégées trois fois : globalement (toutes les paires), sur les paires validées seules, et sur
   les non-validées seules (`None` quand ce sous-ensemble est vide) - pour distinguer "le
   retrieval est mauvais" de "ces questions n'ont jamais été relues".

Le suivi de progression/logs passe par une `Task` (même mécanisme que
`worker/document_process`), mais créée directement par le backend au moment du déclenchement
(`EvaluationService.trigger`) plutôt que par le worker lui-même : contrairement au pipeline de
documents, ce run n'a pas de tâche enfant à enregistrer, et le backend connaît déjà
l'utilisateur à cet instant.

## Structure

```
app/
  tasks.py          la tâche Celery run_evaluation
  metrics.py         precision@k/recall@k/MRR/nDCG, fonctions pures
  celery_app.py      app Celery (queue, nom de la tâche - doit matcher backend/app/core/tasks.py)
  backend_client.py  client HTTP vers les endpoints /internal/* du backend
  task_logging.py    capture les logs loguru d'un run et les renvoie au backend
  config.py          Settings (voir docs/environment-variables.md)
```

## Développer

```bash
cd worker/evaluation
uv sync
uv run pytest -q               # tests (fake backend client, pas de vrais appels réseau)
uv run ruff check . && uv run ruff format --check .
```

Le worker tourne dans `docker-compose.yaml` sous le service `worker-evaluation`, sur la queue
Celery `evaluation`.
