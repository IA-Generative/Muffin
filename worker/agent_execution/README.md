# worker/agent_execution

Worker Celery qui exécute le graphe LangGraph de l'agent de recherche pour un run donné : de la
question de l'utilisateur jusqu'à une réponse citée, en passant par le planning, la recherche
multi-collections, et une vérification que chaque affirmation est bien étayée par une source
(grounding).

Ne parle jamais directement à Postgres/Qdrant : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`.

## Le graphe (`app/graph/graph.py`)

1. `load_context` / `load_accessible_vdbs` - charge l'historique de conversation et la liste des
   collections auxquelles l'utilisateur a accès (**la** barrière de permission - voir
   `docs/research-agent-plan.md` à la racine du repo : le routing par LLM ne fait que restreindre
   à l'intérieur de cette liste, jamais l'élargir).
2. `analyze_query` - décide si la question nécessite une clarification (`request_clarification`,
   pause human-in-the-loop) ou peut être traitée directement.
3. `decompose_query` / `build_research_plan` - découpe la question en sous-tâches de recherche.
4. `research_task` (fan-out dynamique via `Send`, un nœud par tâche en parallèle, borné par les
   budgets `MAX_PARALLEL_TASKS`/`MAX_PARALLEL_SEARCHES`/...) - exécute un outil par tâche :
   `search`, `page_content`, `list_documents`, `collection_summary`, `list_collections`. Pour
   `search`, cascade QA cache → résumés → chunks (voir `app/graph/nodes/research_task.py`) avant
   de faire une recherche vectorielle complète.
5. `merge_evidence` → `evaluate_coverage` → `replan_research` (boucle bornée par `MAX_REPLANS`) -
   vérifie que les preuves collectées suffisent à répondre, relance une recherche ciblée sinon.
6. `build_answer_context` → `generate_answer` - génère la réponse finale avec citations.
7. `validate_grounding` → `targeted_research` (boucle bornée par `MAX_GROUNDING_RESEARCHES`) -
   vérifie que chaque affirmation citée est bien supportée par une preuve réelle ; relance une
   recherche ciblée sur les affirmations non supportées sinon.

Le graphe peut être annulé (`cancel_requested` sur le run) et repris après une clarification
utilisateur (checkpointer LangGraph sur Redis - une pause doit pouvoir être reprise par un worker
Celery différent de celui qui l'a posée).

## Structure

```
app/
  graph/
    graph.py       assemblage du graphe (add_node / add_conditional_edges)
    state.py       AgentState (état partagé) et ResearchTaskInput (payload du fan-out)
    nodes/         un fichier par nœud du graphe (voir la liste ci-dessus)
    routing/        conditions.py - logique de fan-out et de branchement conditionnel
    services/       llm.py (appels LLM), vdb_router.py (sélection des collections pertinentes),
                    evidence.py, planning.py, document_resolver.py, events.py
  agent_service.py  point d'entrée appelé par la tâche Celery : charge le run, lance le graphe
  backend_client.py client HTTP vers les endpoints /internal/* du backend
  celery_app.py     app Celery (queue, nom des tâches)
  config.py         Settings, dont les budgets d'exécution (voir docs/environment-variables.md)
```

## Développer

```bash
cd worker/agent_execution
uv sync
uv run pytest -q               # tests (fake backend client, pas de vrais appels réseau)
uv run ruff check . && uv run ruff format --check .
```

Le worker tourne dans `docker-compose.yaml` sous le service `worker-agent-execution`, sur la queue
Celery `agent_execution`.
