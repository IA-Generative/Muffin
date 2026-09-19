# worker/evaluation

Worker Celery qui calcule des métriques de qualité pour l'agent - deux tâches distinctes, sur la
même queue :

- `run_evaluation` (voir issue #11) : un run d'évaluation retrieval pour une collection - rejoue
  chaque paire QA à travers la même recherche que l'agent, note la pertinence des résultats,
  génère une réponse, envoie un `EvaluationRun` complet au backend.
- `score_discussion` (voir issue #31) : un jugement de qualité sur une conversation entière -
  cohérence entre les tours, bonne exploitation du contexte conversationnel - envoie un
  `DiscussionScore` au backend.

Ne parle jamais directement à Postgres/Meilisearch : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`.

Dans sa propre queue Celery (`evaluation`), séparée de `document_processing` et
`agent_execution` : un run d'évaluation itère sur toutes les paires QA d'une collection, refait une
recherche + une génération pour chacune - potentiellement long et gourmand en appels LLM, ça ne
doit jamais faire attendre une vraie requête utilisateur ni retarder l'ingestion de documents.
`score_discussion` est un seul appel LLM par conversation, beaucoup plus léger, mais partage cette
même queue plutôt que d'avoir son propre service - pas assez de volume pour le justifier.

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

## Ce que fait `score_discussion` (`app/tasks.py`)

1. Récupère le transcript complet de la conversation (`/internal/conversations/{id}/messages`).
   Ignore les conversations avec moins de 2 tours assistant : sans au moins deux réponses, il n'y
   a rien à comparer entre les tours.
2. Envoie le transcript au modèle de chat par défaut du hub LLM, avec une consigne qui juge deux
   choses indépendamment : la cohérence (contradictions entre les réponses) et l'exploitation du
   contexte conversationnel (une question de suivi qui dépend d'un tour précédent est-elle bien
   résolue). Réponse attendue en JSON structuré - un JSON mal formé ou une réponse refusée
   retombe sur un verdict conservateur ("aucun problème trouvé") plutôt que de faire planter la
   tâche ou d'inventer un problème que le modèle n'a jamais vraiment signalé.
3. Poste un unique `DiscussionScore` au backend.

Le suivi de progression/logs pour les deux tâches passe par une `Task` (même mécanisme que
`worker/document_process`), mais créée directement par le backend au moment du déclenchement
(`EvaluationService.trigger` / `ConversationService.trigger_discussion_score`) plutôt que par le
worker lui-même : ni l'une ni l'autre n'a de tâche enfant à enregistrer, et le backend connaît
déjà l'utilisateur à cet instant.

## Structure

```
app/
  tasks.py          les tâches Celery run_evaluation et score_discussion
  metrics.py         precision@k/recall@k/MRR/nDCG, fonctions pures
  celery_app.py      app Celery (queue, noms des tâches - doit matcher backend/app/core/tasks.py)
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
