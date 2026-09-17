from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.graph import AgentState, build_graph

_graph = build_graph()


def _config(run_id: str) -> dict[str, Any]:
    # thread_id = run_id: the checkpointer keys a run's full state (incl. any HITL pause) by
    # this, so resuming later re-enters the same graph execution rather than starting fresh.
    return {"configurable": {"thread_id": run_id}}


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
            initial_state: AgentState = {
                "run_id": run_id,
                "user_id": run["user_id"],
                "conversation_id": run["conversation_id"],
                "original_query": run["query"],
                "messages": [{"role": "user", "content": run["query"]}],
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
        """Entry point for continuing a run paused on request_clarification's interrupt() (§31).
        Not wired to an API route yet (out of scope for this iteration - LangGraph orchestration
        only); a future `POST /runs/{id}/resume` calls this the same way `run` is called today."""
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
            backend_client.add_run_event(run_id, "run_waiting_for_user", {"interrupt": interrupt_payload})
            return

        if final_state.get("cancelled"):
            backend_client.update_run_status(run_id, "cancelled")
            backend_client.add_run_event(run_id, "run_cancelled")
            return

        backend_client.set_run_result(run_id, final_state["answer"] or "", final_state["citations"])
        backend_client.update_run_status(run_id, "completed")
        backend_client.add_run_event(run_id, "run_completed", {"citation_count": len(final_state["citations"])})


agent_service = AgentService()
