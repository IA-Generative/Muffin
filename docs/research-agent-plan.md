# Research agent — plan

Tracks the staged implementation of the research agent (LangGraph-orchestrated,
Celery-executed, multi-knowledge-base) per the architecture brief. Updated as each
step below completes — see "Méthode d'implémentation" for the step list.

## Étape 1 — Audit (done)

### EXISTANT

**Celery** (producer/consumer pattern to duplicate, not reinvent)
- Producer: `backend/app/core/tasks.py` — `Celery("muffin_backend_producer", broker=REDIS_URL, backend=REDIS_URL)`,
  `result_expires=7d`, `send_task(..., queue="document_processing")`, returns the `celery_task_id`.
- Consumer: `worker/document_process/app/celery_app.py` (`task_track_started=True`, `task_acks_late=True`,
  `task_time_limit=300`) + `worker/document_process/app/tasks.py` (6 chained tasks, `bind=True`, each spawns
  children via `_spawn()` which registers a `Task` row with `parent_celery_task_id`).
- `worker/agent_execution/` already exists as a scaffold (Dockerfile prints "not implemented yet",
  empty `pyproject.toml`/`app/__init__.py`) — the separate worker for graph execution the plan calls for.
  Deployed as a 4th Helm component (`helm/values.yaml`), which also declares a `qdrant` dependency
  (`helm/Chart.yaml`, `condition: qdrant.enabled`) — infra anticipates this feature, app code doesn't yet.

**Run tracking** (generic lifecycle already built, reusable directly)
- `backend/app/models/task.py`: `Task` with `celery_task_id`, `task_name`, `owner_id`, `document_id`/
  `collection_id` (nullable), `parent_id` (self-FK), `logs` (Text). No persisted status — read live from
  Celery (`get_task_status`).
- `TaskRepository`/`TaskService`/`app/routers/tasks.py`: pagination by root run (not raw rows),
  `GET /api/tasks`, `POST /api/tasks/{id}/revoke`, `GET /api/tasks/{id}/logs`.
- `capture_task_logs()` (`worker/.../task_logging.py`): per-task loguru sink, reported to the backend
  on both success and failure.

**Auth/permissions**
- `RequestContext` (`backend/app/core/security/factory.py`): `user_id, email, roles, is_admin,
  first_name, last_name`, sourced from Keycloak userinfo, never the client.
- Ownership is strictly owner-only: `CollectionRepository.get(collection_id, owner_id)`. `CollectionShare`/
  `ShareSubjectType` (`backend/app/models/collection.py`) are defined and exported but never queried or
  written anywhere — a dead model, no real multi-user ACL today.
- `/api/internal/*` is protected by a shared API key (`require_worker_api_key`), not Keycloak — that's
  the worker→backend channel.

**Persistence / repository-service-router**
- Established pattern everywhere: Repository (async SQLAlchemy) → Service (business rules + ownership
  check) → Router (FastAPI, maps exceptions to HTTP). Generic pagination `Page[T]`/`PaginationParams`
  (`app/schemas/pagination.py`).

**Conversation/Message** (modeled, never wired)
- `Conversation`, `Message` (`role: user|assistant`), `Source`, `MessageSource`, `Feedback` exist in the
  DB (`backend/app/models/conversation.py`, `message.py`, `source.py`) but no router/service touches
  them. Frontend `useChat.ts` is fully mocked.

**LLM**
- Per-router OpenAI-compatible client (`app/routers/models.py`, `app/routers/internal_llm.py`) — no
  function/tool-calling, hardcoded prompts, plain chat/embedding calls.
- The document pipeline is a real hand-rolled DAG with fan-out/fan-in (`chunk_document` →
  `{summarize_document → {tag_document, update_collection_description → generate_collection_qa,
  update_collection_tags}, generate_qa_window×N, extract_entities_window×N}`), just expressed as
  self-chaining Celery tasks, not a LangGraph graph.
- `QaPair`, `Entity`, `Relation` already are the "Evidence" concept with provenance (nullable
  `document_id`, `collection_id`, text, type) — no `relevance_score`/`retrieval_query` yet.

**Tests**
- Convention: `httpx.AsyncClient` + `ASGITransport`, never the sync `TestClient` (asyncpg/event-loop
  incompatibility). Fixture teardown deletes rows by model.

### MANQUANT
- LangGraph / LangChain: zero reference anywhere in the repo.
- A2A: zero reference anywhere.
- A "VDB"/"knowledge base" concept distinct from `Collection`: doesn't exist (one granularity today).
- Tool/function-calling for the LLM: doesn't exist.
- SSE/WebSocket: doesn't exist — everything is polling today.
- `POST /runs`, `GET /runs/{id}`: don't exist.
- Cooperative cancellation (persisted flag checked by nodes): doesn't exist — today's `revoke_task` is
  a plain Celery `terminate=True`.
- Explicit run status (QUEUED/RUNNING/WAITING_FOR_USER/...): doesn't exist, only Celery's own
  PENDING/STARTED/SUCCESS/FAILURE/REVOKED.

### À CONSERVER
- Repository/Service/Router pattern as-is.
- `Task`/`TaskRepository`/`TaskService`/`/api/tasks` as-is — already the generic run-tracking asked for,
  just missing a persisted `status` and the run-specific fields (plan, evidence, budget...).
- The Celery producer/worker pattern (`app/core/tasks.py` + `celery_app.py`) — duplicated identically for
  `agent_execution`, new queue, same conventions (`result_expires`, `task_track_started`).
- `RequestContext`/Keycloak as the only identity source — never a `user_id` from the LLM or payload.
- The `worker/agent_execution/` scaffold — fill it in, don't redefine its structure.
- `Conversation`/`Message`/`Source` as the base of the "conversation" state, kept separate from
  "execution" state — they exist, just never wired.
- `QaPair`/`Entity`/`Relation` as the starting point for "Evidence", extended rather than duplicated.

### À REFACTORER
- `CollectionShare`: either wire it for real (query it in `CollectionRepository.list_by_owner`/`get`) or
  remove it from the path — a future permission-based VDB routing that stays owner-only would be trivial
  but wouldn't match the brief's intent if sharing is meant to be real.
- `Task.logs` with no persisted `status`: a long run with HITL/resume needs a genuinely persisted status,
  not one derived from Celery, or a restarted worker / `WAITING_FOR_USER` run loses its state.
- `revoke_task` (`terminate=True`) needs a cooperative path for agent runs (a persisted flag nodes check),
  without breaking its current use for `process_document` (which can keep `terminate=True`).

### À AJOUTER
- `langgraph` (+ `langchain-core` if used for tools) in `worker/agent_execution/pyproject.toml`.
- Models: `Run` (persisted status, plan, budget, plan_version, replan_count, cancel_requested,
  timestamps), plus a structured-events table (`RunEvent`?, TBD at Étape 2).
- Producer `enqueue_run_agent(run_id)` (new `backend/app/core/agent_tasks.py` or extension of
  `core/tasks.py`), new `agent_execution` queue.
- `POST /api/runs`, `GET /api/runs/{id}` (+ SSE/polling for events).
- Server-controlled tools (`list_accessible_vdbs`, `search_knowledge_base`, ...) that re-validate
  permissions on every call — never trust the LLM.
- The LangGraph graph itself, in `worker/agent_execution/app/`.

## Étape 2 — Architecture (done, LangGraph scope only)

Boundaries: Celery/A2A/API/frontend/infra are untouched this iteration - only
`worker/agent_execution/app/graph/` changed. Layout: `state.py` (AgentState +
ResearchTask/Evidence/CoverageResult/GroundingResult), `graph.py` (wiring), `nodes/` (one
per orchestration step, §35 - no node per internal service call), `routing/conditions.py`
(all conditional-edge functions, including the dynamic `Send`-based fan-out), `services/`
(vdb_router, evidence normalization, planning, llm helpers - plain functions research_task
calls, not graph nodes themselves).

## Étape 3 — Research DAG (done)

Graph now matches the target shape: `load_context → load_accessible_vdbs → analyze_query
→ (request_clarification interrupt if ambiguous) → decompose_query → build_research_plan
→ [dynamic fan-out] → research_task × N → merge_evidence → (loop back into the fan-out gate
for any task whose dependency just completed) → evaluate_coverage → (insufficient →
replan_research → back into the fan-out) → build_answer_context → generate_answer →
validate_grounding → (invalid → targeted_research → merge_evidence again) → END`.

- **VDB = Collection** in this codebase (audit finding, §7 of the brief) - no separate
  knowledge-base grouping exists yet, so `load_accessible_vdbs`/`vdb_routing` reuse
  `list_accessible_collections` rather than inventing a parallel concept; revisit if a real
  multi-collection VDB grouping is ever introduced.
- Permission barrier preserved and reused: `select_relevant_vdbs` only ever intersects the
  LLM's picks against `accessible_vdbs`, never widens it (tested in `test_graph.py`).
- Reducers: `research_tasks` merges by id (parallel branches update their own task without
  clobbering others' status), `evidence`/`completed_task_ids`/`failed_task_ids` accumulate
  via `operator.add`. `deduped_evidence` is a separate derived field, not a rewrite of
  `evidence` - overwriting a reducer-backed field from a node would double-apply the reducer.
  `research_task` runs under its own narrower `ResearchTaskInput` schema so a branch never
  sees the other tasks.
- Budgets added to `config.py`: `MAX_PARALLEL_TASKS`, `MAX_TOTAL_TASKS`, `MAX_REPLANS`,
  `MAX_GROUNDING_RESEARCHES` (existing `MAX_PARALLEL_SEARCHES`/`MAX_TOTAL_SEARCHES` kept).
- Cancellation checked at the top of every node via the existing `cancel_requested` flag;
  every edge routes through `route_or_cancel`/the fan-out routers so a cancellation is
  honored between any two steps, not just at fixed checkpoints.
- HITL wired with LangGraph's native `interrupt()`/`Command(resume=...)` in
  `request_clarification`, backed by `InMemorySaver` for now - swapping in a Postgres
  checkpointer is an infra change, out of scope here, but every node already reads/writes
  through `AgentState` so that swap is a one-line change in `graph.py` later.
- `AgentService.resume(run_id, answer)` exists as the future entry point for continuing a
  paused run once an API route exists to call it - not wired to Celery/HTTP yet.
- Tests: `worker/agent_execution/tests/test_graph.py`, all 10 scenarios from the brief's
  §36 (simple query, parallel decomposition, dependency ordering, VDB permission barrier,
  multi-VDB fan-out, failure isolation, targeted replan, grounding-triggered targeted
  research, HITL interrupt/resume, cancellation) against a fake `backend_client`.

## Étape 4 — Vector search (Qdrant) (done)

`ChunkRepository.search`'s Postgres full-text search is replaced by real vector search - the
gap the audit above used to call out is closed:

- **Storage**: one Qdrant collection per Muffin `Collection` (`chunks_{collection_id}`,
  `app/services/vector_store.py`), created lazily on the first embedded chunk with whatever
  vector size that collection's own `embedding_model` produces. Never one global Qdrant
  collection - keeps per-collection deletion trivial and never mixes two collections'
  potentially different embedding dimensions.
- **Embedding at ingestion**: `worker/document_process`'s `chunk_document` task now embeds
  each chunk (via the existing `POST /api/internal/llm/embed`, using the collection's own
  `embedding_model` setting - previously dead config, now actually consumed) and sends the
  vector alongside the chunk in `POST /api/internal/documents/{id}/chunks`. Best-effort: an
  embedding failure (e.g. no LLM hub configured) logs and leaves that chunk merely
  unsearchable, it doesn't fail the pipeline - same convention as the existing
  collection-description embedding step.
- **Backend storage**: `DocumentService.add_chunk` upserts into Qdrant right after the
  Postgres `Chunk` row commits (`document_service.py`), point id = chunk id.
- **Search**: `app/services/search_service.py` groups the selected collections by embedding
  model (a collection's chunks are only ever compared within their own Qdrant collection, so -
  unlike the collection-description embedding, which must stay in one global embedding space
  to be comparable across collections - each collection can use its own model), embeds the
  query once per distinct model, queries each collection's own Qdrant collection, merges by
  score, and hydrates the winning chunk ids back into `Chunk`/`Document` rows for text/name.
  `POST /api/internal/search` (used by the agent's `research_task`/VDB routing) now calls this
  instead of `ChunkRepository.search`.
- **Deletion**: `CollectionService.delete_collection` now also deletes that collection's Qdrant
  collection (best-effort, same reasoning as the existing RustFS object cleanup).
- **Local dev**: `docker-compose.yaml` gains a `qdrant` service (`qdrant/qdrant:v1.15.5`,
  named volume, healthcheck) and `QDRANT_URL` on `backend` - the worker never talks to Qdrant
  directly, only the backend does. `/api/health` reports Qdrant alongside redis/database.
- Tests: `backend/tests/routers/test_internal_documents.py` (chunk embedding upsert,
  no-embedding no-op), `test_internal_runs.py` (search hydration), `test_health.py`, and
  `worker/document_process/tests/test_tasks.py` (embed-per-chunk, failure tolerance) - all
  against a faked `vector_store`/`_openai_client`, no live Qdrant/LLM hub needed to run them.

## Étape 4bis — Knowledge-base introspection tools (done)

The graph could only ever answer content questions (search). It now also answers questions
*about* the knowledge bases themselves - "how many collections/documents do I have", "summarize
collection X", "how many documents are in Y", "give me the text/screenshot of page N of
document Z" - without ever letting an LLM-chosen id escape the permission barrier:

- `analyze_query` gained a fourth intent, `"meta"`, so `decompose_query` doesn't take its
  simple-single-source shortcut (which always hardcoded `tool="search"`) for these queries -
  it always asks the LLM, which now also picks a `tool` per task: `search` (default),
  `list_collections`, `collection_summary`, `list_documents`, `page_content`.
- `research_task` dispatches on `task["tool"]` (`app/graph/nodes/research_task.py`) - still one
  node, not one per tool (§35): `list_collections`/`collection_summary` read straight from
  `accessible_vdbs` (no backend call at all - the count is already in that list, see below);
  `list_documents`/`page_content` resolve a target collection the same way search resolves VDBs
  (`select_relevant_vdbs`, intersected against `accessible_vdbs`), then call the two new
  backend endpoints below scoped to that collection. `page_content` additionally resolves which
  document/page via `app/graph/services/document_resolver.py`, which intersects the LLM's pick
  against the *candidate document list the backend already scoped to this user* - never an id
  the LLM invents.
- Backend: `AccessibleCollectionOut` gained `document_count` (`CollectionRepository.count_documents`,
  one grouped query) - `list_collections`/`collection_summary` need no new endpoint at all.
  Two new ownership-checked endpoints on `/api/internal/runs`'s router: `GET
  /users/{user_id}/collections/{collection_id}/documents` (name/status/summary per document) and
  `GET /users/{user_id}/documents/{document_id}/pages/{page_number}` (page text + a presigned
  RustFS screenshot URL, `storage.get_presigned_url`) - both 404 if the collection isn't owned
  by `user_id`, same barrier as `accessible-collections`.
- Tests: `backend/tests/routers/test_internal_runs.py` (document_count, both new endpoints,
  ownership rejection) and `worker/agent_execution/tests/test_graph.py` (one test per tool,
  verifying no `search` call happens for the non-search tools and that evidence carries the
  right `source_id`/`vdb_id`).

## Étape 5-10

Not started: Celery re-wiring beyond the existing single `agent_service.run()` entry
point, A2A, the actual `/resume` API route, SSE/UI event consumption, a Postgres
checkpointer for the LangGraph runs, and real multi-collection VDB grouping if that's
ever introduced.
