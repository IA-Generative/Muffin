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
- Qdrant in code: zero import/client, only a TODO comment + the Helm dependency.
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

## Étape 2 — Architecture (not started)

Boundaries to define: API / Celery / Agent Service / LangGraph / Knowledge services /
Persistence / Events / A2A.

## Étape 3-10

Not started. See the architecture brief for the full step list (run lifecycle, research
DAG, VDB routing, evidence/grounding, HITL/cancellation, events/UI, A2A, tests).
