# worker/agent_execution

Worker Celery qui exécute le graphe LangGraph de l'agent de recherche pour un run donné : de la
question de l'utilisateur jusqu'à une réponse citée, en passant par le planning, la recherche
multi-collections, et une vérification que chaque affirmation est bien étayée par une source
(grounding).

Ne parle jamais directement à Postgres/Meilisearch : toute lecture/écriture passe par les endpoints
internes du backend (`app/backend_client.py`), authentifiés par `WORKER_API_KEY`. Seule exception :
SearXNG (`app/searxng_client.py`), appelé directement par l'outil `web_search`, jamais via le
backend - aucune donnée utilisateur n'y est stockée, ce n'est qu'un aller-retour HTTP.

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
   `search`, `page_content`, `list_documents`, `collection_summary`, `list_collections`,
   `web_search`. Pour `search`, cascade QA cache → résumés → chunks (voir
   `app/graph/nodes/research_task.py`) avant de faire une recherche vectorielle complète.
   `web_search` (SearXNG) n'est jamais proposé au planner ni exécuté sauf si le run a activé la
   recherche web (toggle du composer de chat, désactivé par défaut - voir
   `AgentState.web_search_enabled`, double vérification dans `decompose_query.py` et
   `research_task.py`).
5. `merge_evidence` → `evaluate_coverage` → `replan_research` (boucle bornée par `MAX_REPLANS`) -
   vérifie que les preuves collectées suffisent à répondre, relance une recherche ciblée sinon.
6. `build_answer_context` → `generate_answer` - génère la réponse finale avec citations.
7. `validate_grounding` → `targeted_research` (boucle bornée par `MAX_GROUNDING_RESEARCHES`) -
   vérifie que chaque affirmation citée est bien supportée par une preuve réelle ; relance une
   recherche ciblée sur les affirmations non supportées sinon.

Le graphe peut être annulé (`cancel_requested` sur le run) et repris après une clarification
utilisateur (checkpointer LangGraph sur Redis - une pause doit pouvoir être reprise par un worker
Celery différent de celui qui l'a posée).

## Pièges connus

Deux bugs rencontrés en ajoutant `web_search`, tous deux invisibles en tests unitaires - seul un
run réel de bout en bout contre la stack dev (utilisateur sans aucune collection accessible,
`web_search_enabled=true`) les a fait apparaître : la réponse revenait sans aucune citation
`web_search`, alors que l'outil aurait dû être utilisé.

- **`replan_research.py` figeait `tool="search"` pour toute tâche replanifiée.** La boucle
  "couverture insuffisante → replan" (`evaluate_coverage` → `replan_research`) est justement le
  scénario principal décrit pour déclencher `web_search` (accès documentaire épuisé), mais elle ne
  pouvait jamais l'atteindre puisque le tool était toujours forcé à `"search"`. Corrigé en laissant
  le LLM choisir l'outil parmi le même ensemble activé/désactivé que `decompose_query.py`.
- **`evaluate_coverage.py` classait un jeu de preuves 100% `web_search` comme une simple recherche
  "meta" (au même titre que `list_collections`/`collection_summary`/...), donc jugée complète sans
  évaluation de pertinence.** Un résultat web est une preuve de contenu au même titre qu'un chunk
  de document, pas une recherche méta - il doit passer par le même jugement de suffisance. Corrigé
  via l'ensemble `_CONTENT_TOOLS = {"search", "web_search"}`.

À garder en tête pour tout futur outil de type "recherche" ajouté au graphe : vérifier qu'il est
bien atteignable depuis la boucle de replan, et bien classé côté `evaluate_coverage` - un test
unitaire isolé sur le node concerné ne suffit pas à le détecter, il faut un run bout en bout qui
passe réellement par la boucle replan.

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
  searxng_client.py client HTTP vers SearXNG (outil web_search, appelé directement, pas via le backend)
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
