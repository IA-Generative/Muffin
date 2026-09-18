from typing import Any

from langgraph.checkpoint.redis import RedisSaver
from loguru import logger

from app.backend_client import backend_client
from app.config import settings
from app.graph import AgentState, build_graph

# Redis-backed, not the graph's default InMemorySaver (§32): a HITL pause (request_clarification's
# interrupt()) is resumed by whichever Celery prefork child picks up the resume_agent task, which
# is almost never the same process that ran interrupt() - only a checkpointer outside any single
# process's memory can survive that. Requires RediSearch (redis-stack-server, not plain redis).
try:
    _checkpointer = RedisSaver(redis_url=settings.REDIS_URL)
    _checkpointer.setup()
except Exception:
    # Falls back to build_graph()'s in-process default - fine for tests/local dev without a real
    # redis-stack reachable, but means a HITL pause can't survive a resume on another process
    # (or a worker restart) until this connects. Never crash the whole worker over it at import.
    logger.exception("Failed to set up the Redis checkpointer - falling back to an in-memory one")
    _checkpointer = None
_graph = build_graph(checkpointer=_checkpointer)

_TITLE_SYSTEM_PROMPT = (
    "Summarize the following question and answer into a short, specific conversation title - at "
    "most 6 words, no surrounding quotes, no trailing punctuation, same language as the question."
)


def _config(run_id: str) -> dict[str, Any]:
    # thread_id = run_id: the checkpointer keys a run's full state (incl. any HITL pause) by
    # this, so resuming later re-enters the same graph execution rather than starting fresh.
    return {"configurable": {"thread_id": run_id}}


def _generate_conversation_title(conversation_id: str, query: str, answer: str) -> None:
    """Best-effort (§ never let a side effect flip an already-completed run to failed): the
    backend's own title_generated flag makes this idempotent, so it's safe to just attempt it
    after every completed run rather than the worker tracking "is this the first one" itself."""
    try:
        model = backend_client.get_default_chat_model()
        if model is None:
            return
        title = backend_client.llm_chat(
            model,
            [
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {query}\n\nAnswer: {answer}"},
            ],
        )
        title = title.strip().strip('"').strip("'")[:80]
        if title:
            backend_client.update_conversation_title(conversation_id, title)
    except Exception:
        logger.exception(f"Failed to generate a title for conversation {conversation_id}")


class AgentService:
    """Thin orchestration layer between the Celery task and LangGraph - loads
    the run, builds its initial state, invokes the graph, and persists the
    outcome. The graph itself (app/graph/) owns all research/decision
    logic; this stays dumb on purpose so Celery/A2A callers never need to
    know anything about LangGraph."""

    def run(self, run_id: str) -> None:
        run = backend_client.get_run(run_id)

        if run["status"] in ("completed", "cancelled"):
            # Idempotency (§8): a redelivered Celery message must not redo
            # work or duplicate events for a run that already reached a
            # terminal state.
            logger.info(f"Run {run_id} is already {run['status']}, skipping")
            return

        try:
            # Prior turns of this same conversation (oldest first, the run's own query excluded -
            # see GET /api/internal/runs/{run_id}) - without these, a follow-up like "elle parle
            # de quoi ?" has no way to resolve what "elle" refers to; see analyze_query.
            history = [{"role": item["role"], "content": item["content"]} for item in run.get("history") or []]
            initial_state: AgentState = {
                "run_id": run_id,
                "user_id": run["user_id"],
                "conversation_id": run["conversation_id"],
                "original_query": run["query"],
                "contextualized_query": run["query"],
                "messages": [*history, {"role": "user", "content": run["query"]}],
                # Fetched once here rather than by every node that needs it (see AgentState.chat_model) -
                # backend_client.get_default_chat_model() is already Redis-cached backend-side, so this
                # is the only worker<->backend round trip for it in the entire run.
                "chat_model": backend_client.get_default_chat_model(),
                "accessible_vdbs": [],
                "query_analysis": {},
                "research_plan": {},
                "research_tasks": [],
                "completed_task_ids": [],
                "failed_task_ids": [],
                "evidence": [],
                "deduped_evidence": [],
                "coverage_result": None,
                "plan_version": run.get("plan_version", 0),
                "replan_count": run.get("replan_count", 0),
                "answer_context": None,
                "answer": None,
                "citations": [],
                "grounding_result": None,
                "grounding_research_count": 0,
                "execution_status": "queued",
                "cancelled": False,
            }
            final_state = _graph.invoke(initial_state, config=_config(run_id))
            self._finalize(run_id, final_state)
        except Exception as error:
            logger.exception(f"Run {run_id} failed")
            backend_client.set_run_error(run_id, str(error))
            backend_client.update_run_status(run_id, "failed")
            backend_client.add_run_event(run_id, "run_failed", {"error": str(error)})
            raise

    def resume(self, run_id: str, answer: str) -> None:
        """Entry point for continuing a run paused on request_clarification's interrupt() (§31),
        called from app.tasks.resume_agent (dispatched by POST /api/runs/{id}/resume)."""
        from langgraph.types import Command

        try:
            final_state = _graph.invoke(Command(resume=answer), config=_config(run_id))
            self._finalize(run_id, final_state)
        except Exception as error:
            logger.exception(f"Run {run_id} failed to resume")
            backend_client.set_run_error(run_id, str(error))
            backend_client.update_run_status(run_id, "failed")
            backend_client.add_run_event(run_id, "run_failed", {"error": str(error)})
            raise

    def _finalize(self, run_id: str, final_state: dict[str, Any]) -> None:
        if final_state.get("__interrupt__"):
            interrupt_payload = final_state["__interrupt__"][0].value
            backend_client.update_run_status(run_id, "waiting_for_user")
            # Persisted on the Run row itself, not just the event log - RunOut exposes it so the
            # frontend can show the question without also having to fetch /events.
            backend_client.update_run_state(run_id, pending_human_action=interrupt_payload)
            backend_client.add_run_event(run_id, "run_waiting_for_user", {"interrupt": interrupt_payload})
            return

        if final_state.get("cancelled"):
            backend_client.update_run_status(run_id, "cancelled")
            backend_client.add_run_event(run_id, "run_cancelled")
            return

        backend_client.set_run_result(run_id, final_state["answer"] or "", final_state["citations"])
        backend_client.update_run_status(run_id, "completed")
        backend_client.add_run_event(run_id, "run_completed", {"citation_count": len(final_state["citations"])})
        _generate_conversation_title(
            final_state["conversation_id"], final_state["original_query"], final_state["answer"] or ""
        )


agent_service = AgentService()
