# worker/evaluation

Worker Celery qui calcule des métriques de qualité pour l'agent - deux tâches distinctes, sur la
même queue :

- `run_evaluation` (voir issue #11) : un run d'évaluation pour une collection - rejoue chaque paire
  QA à travers le pipeline (recherche + génération) et fait noter chaque réponse générée deux fois
  par un juge LLM (factualité face à la réponse attendue, fidélité au contexte réellement récupéré),
  le tout orchestré par [promptfoo](https://www.promptfoo.dev/docs/intro/).
- `score_discussion` (voir issue #31) : un jugement de qualité sur une conversation entière -
  cohérence entre les tours, bonne exploitation du contexte conversationnel - envoie un
  `DiscussionScore` au backend.

Ne parle jamais directement à Postgres/Qdrant : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`.

Dans sa propre queue Celery (`evaluation`), séparée de celles de worker/document_process et
`agent_execution` : un run d'évaluation rejoue toutes les paires QA d'une collection - une recherche
+ une génération + deux jugements pour chacune, potentiellement long et gourmand en appels LLM, ça ne
doit jamais faire attendre une vraie requête utilisateur ni retarder l'ingestion de documents.
`score_discussion` est un seul appel LLM par conversation, beaucoup plus léger, mais partage cette
même queue plutôt que d'avoir son propre service - pas assez de volume pour le justifier.

## Ce que fait `run_evaluation` (`app/tasks.py`)

1. Récupère les paramètres de la collection (chunking/embedding, modèle configuré pour
   l'étape `evaluation` si défini, sinon le modèle de chat par défaut du hub LLM - ce sera le
   juge ; le générateur est toujours le modèle de chat par défaut).
2. Récupère les paires QA de la collection (validées seulement si `validated_only`). Une paire
   sans document source (`document_id`) est ignorée : sans document, la recherche n'a rien à
   retourner et le juge n'a pas de contexte.
3. Si un run identique existe déjà (même empreinte SHA-256 des paires QA + paramètres de
   chunking + embedding + k + juge + générateur + métriques notées), la tâche s'arrête là -
   pas de doublon.
4. Écrit un répertoire d'évaluation temporaire : `pairs.json` (les paires à évaluer), le YAML
   `promptfooconfig.yaml` et les deux modules qu'il référence (`provider.py`, `create_tests.py`,
   copiés depuis `app/promptfoo/`).
5. Lance la CLI promptfoo (`promptfoo eval --config promptfooconfig.yaml --output results.json
   --output report.html --no-cache --no-write --no-progress-bar --no-table`). promptfoo exécute
   alors, pour chaque paire :
   - le **provider** (`app/promptfoo/provider.py`) : recherche les `k` chunks via le même
     endpoint `/internal/search` que l'agent, puis génère une réponse via `/internal/llm/chat` ;
   - le **juge** : le modèle d'évaluation de la collection, appelé à travers le proxy
     OpenAI-compatible du backend (`/api/internal/v1`, voir `backend/app/routers/
     internal_openai_compat.py`) avec deux assertions promptfoo par paire (seuil 0.7 chacune,
     couleur - un score bas n'élimine jamais un résultat) :
     - `factuality` : la réponse générée est-elle cohérente avec la réponse attendue ?
     - `context-faithfulness` : la réponse générée est-elle ancrée dans le contexte que le
       pipeline a réellement récupéré (`contextTransform: output.context` - les chunks
       renvoyés par le provider, pas une référence statique) ? La var de test s'appelle
       `query` car les assertions RAG de promptfoo l'exigent.
6. Poste un `EvaluationRun` au backend (compteurs lus depuis le `results.json` produit - l'artefact
   est la vérité), puis y téléverse les deux artefacts : `results.json` et `report.html`, stockés
   dans RustFS par le backend (`evaluations/{run_id}/…`). Le modèle n'a pas d'état "en cours"
   (pas de colonne `status`), donc rien n'est créé avant que promptfoo ait réussi - promptfoo
   sort avec le code 100 quand des tests échouent, c'est un résultat d'évaluation comme un autre,
   pas une erreur.

La clé d'API n'est jamais écrite dans le YAML : promptfoo rejoue toute sa configuration dans le
`results.json` stocké, donc le provider lit la clé depuis sa variable d'environnement
(`api_key_envar`, héritée du worker) et le juge passe par `apiKeyEnvar`.

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
  promptfoo/        les modules référencés par le YAML généré :
    provider.py       le "modèle" évalué : recherche + génération via le backend
    create_tests.py   construit les tests promptfoo depuis pairs.json
  celery_app.py      app Celery (queue, noms des tâches - doit matcher backend/app/core/tasks.py)
  backend_client.py  client HTTP vers les endpoints /internal/* du backend
  task_logging.py    loguru partout, et les logs de chaque run envoyés au backend en direct (#305)
  config.py          Settings (voir docs/environment-variables.md)
```

## Développer

```bash
cd worker/evaluation
uv sync
uv run pytest -q               # tests (fake backend client et CLI promptfoo factice, pas de vrais appels réseau)
uv run ruff check . && uv run ruff format --check .
```

Le worker tourne dans `docker-compose.yaml` sous le service `worker-evaluation`, sur la queue
Celery `evaluation`. Son image embarque le runtime Node et la CLI promptfoo (version épinglée par
`ARG PROMPTFOO_VERSION` dans le `Dockerfile`) - le conteneur ne télécharge rien à l'exécution.
