import asyncio
from typing import Any

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from loguru import logger

from app.agent.ask_user import question_rounds
from app.agent.backend_client import backend_client
from app.agent.config import settings
from app.agent.graph import AgentState, build_graph
from app.agent.graph.nodes.ground_check import ground_check

_graph = None
_graph_lock: asyncio.Lock | None = None


async def _get_graph():
    """The graph, built when the first run needs it (not when the backend imports this module: connecting to Redis then
    would hold up, or break, every start of the backend).

    Redis-backed checkpointer, not the graph's default InMemorySaver (§32): a run that waited for an answer before
    #344 is resumed by whichever backend pod receives the request, which is almost never the one that paused it - only
    a checkpointer outside any single process's memory survives that. Requires RediSearch (redis-stack-server, not
    plain redis). Without it the graph falls back to the in-process default: fine for tests and local dev, but such a
    run cannot be resumed on another process."""
    global _graph, _graph_lock
    if _graph_lock is None:
        _graph_lock = asyncio.Lock()
    async with _graph_lock:
        if _graph is None:
            try:
                checkpointer = AsyncRedisSaver(redis_url=settings.REDIS_URL)
                await checkpointer.asetup()
            except Exception:
                logger.exception("Failed to set up the Redis checkpointer - falling back to an in-memory one")
                checkpointer = None
            _graph = build_graph(checkpointer=checkpointer)
        return _graph


_TITLE_SYSTEM_PROMPT = (
    "Summarize the following question and answer into a short, specific conversation title - at "
    "most 6 words, no surrounding quotes, no trailing punctuation, same language as the question."
)


def _config(run_id: str) -> dict[str, Any]:
    # thread_id = run_id: the checkpointer keys a run's full state (incl. any HITL pause) by
    # this, so resuming later re-enters the same graph execution rather than starting fresh.
    return {"configurable": {"thread_id": run_id}}


async def _generate_conversation_title(conversation_id: str, query: str, answer: str) -> None:
    """Best-effort (§ never let a side effect flip an already-completed run to failed): the
    backend's own title_generated flag makes this idempotent, so it's safe to just attempt it
    after every completed run rather than the worker tracking "is this the first one" itself.
    """
    try:
        model = await backend_client.get_default_chat_model()
        if model is None:
            return
        title = await backend_client.llm_chat(
            model,
            [
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {query}\n\nAnswer: {answer}"},
            ],
        )
        title = title.strip().strip('"').strip("'")[:80]
        if title:
            await backend_client.update_conversation_title(conversation_id, title)
    except Exception:
        logger.exception(f"Failed to generate a title for conversation {conversation_id}")


class AgentService:
    """Thin orchestration layer between the runner and LangGraph - loads
    the run, builds its initial state, invokes the graph, and persists the
    outcome. The graph itself (app/graph/) owns all research/decision
    logic; this stays dumb on purpose so Celery/A2A callers never need to
    know anything about LangGraph."""

    async def run(self, run_id: str) -> None:
        run = await backend_client.get_run(run_id)

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
            raw_history = run.get("history") or []
            history = [{"role": item["role"], "content": item["content"]} for item in raw_history]
            # This message answers the questions the assistant asked last (#344): the event the clients
            # of the run's event stream already know from when the run waited for the answer.
            if raw_history and raw_history[-1].get("asked"):
                await backend_client.add_run_event(run_id, "clarification_received", {"answer": run["query"]})
            initial_state: AgentState = {
                "run_id": run_id,
                "user_id": run["user_id"],
                "user_groups": run.get("user_groups") or [],
                "conversation_id": run["conversation_id"],
                "original_query": run["query"],
                "contextualized_query": run["query"],
                "messages": [*history, {"role": "user", "content": run["query"]}],
                # Fetched once here rather than by every node that needs it (see AgentState.chat_model) -
                # backend_client.get_default_chat_model() is already Redis-cached backend-side, so this
                # is the only worker<->backend round trip for it in the entire run.
                "chat_model": (await backend_client.get_default_chat_model()),
                # Collections explicitly attached via the chat composer's "+" picker - see
                # AgentState.pinned_vdb_ids.
                "pinned_vdb_ids": [str(vdb_id) for vdb_id in (run.get("pinned_collection_ids") or [])],
                "web_search_enabled": bool(run.get("web_search_enabled", False)),
                # See AgentState.resume_from_vdb_ids - set only for a "go further" follow-up.
                "resume_from_vdb_ids": [str(vdb_id) for vdb_id in (run.get("resume_from_collection_ids") or [])],
                # Starts from what pinning already couldn't bring along (#220) - this run's own
                # exploration adds to it, see AgentState.unexplored_vdb_ids.
                "unexplored_vdb_ids": [str(vdb_id) for vdb_id in (run.get("unexplored_collection_ids") or [])],
                "interactive": bool(run.get("interactive", True)),
                "question_rounds": question_rounds(raw_history),
                "questions": None,
                "must_assume": False,
                "accessible_vdbs": [],
                "catalogue": [],
                "edit_candidates": [],
                "create_candidates": [],
                "plan": {},
                "scope_ids": [],
                "widened": False,
                "edit_target": None,
                "edit_proposal": None,
                "create_target": None,
                "query_analysis": {},
                "research_tasks": [],
                "completed_task_ids": [],
                "failed_task_ids": [],
                "evidence": [],
                "deduped_evidence": [],
                "coverage_result": None,
                "answer_context": None,
                "answer": None,
                "citations": [],
                "needs_grounding": False,
                "grounding_result": None,
                "prompt_usages": [],
                "execution_status": "queued",
                "cancelled": False,
            }
            final_state = await (await _get_graph()).ainvoke(initial_state, config=_config(run_id))
            self._finalize(run_id, final_state)
        except Exception as error:
            logger.exception(f"Run {run_id} failed")
            await backend_client.set_run_error(run_id, str(error))
            await backend_client.update_run_status(run_id, "failed")
            await backend_client.add_run_event(run_id, "run_failed", {"error": str(error)})
            raise

    async def resume(self, run_id: str, answer: str) -> None:
        """Entry point for continuing a run paused on request_clarification's interrupt() (§31),
        called by the runner (POST /api/runs/{id}/resume).

        Legacy: request_clarification no longer pauses (#344) - the answer comes with the next message of the
        conversation. Kept for a run that was already waiting when this changed.
        """
        from langgraph.types import Command

        try:
            final_state = await (await _get_graph()).ainvoke(Command(resume=answer), config=_config(run_id))
            self._finalize(run_id, final_state)
        except Exception as error:
            logger.exception(f"Run {run_id} failed to resume")
            await backend_client.set_run_error(run_id, str(error))
            await backend_client.update_run_status(run_id, "failed")
            await backend_client.add_run_event(run_id, "run_failed", {"error": str(error)})
            raise

    async def _finalize(self, run_id: str, final_state: dict[str, Any]) -> None:
        if final_state.get("__interrupt__"):
            interrupt_payload = final_state["__interrupt__"][0].value
            await backend_client.update_run_status(run_id, "waiting_for_user")
            # Persisted on the Run row itself, not just the event log - RunOut exposes it so the
            # frontend can show the question without also having to fetch /events.
            await backend_client.update_run_state(run_id, pending_human_action=interrupt_payload)
            await backend_client.add_run_event(run_id, "run_waiting_for_user", {"interrupt": interrupt_payload})
            return

        if final_state.get("cancelled"):
            await backend_client.update_run_status(run_id, "cancelled")
            await backend_client.add_run_event(run_id, "run_cancelled")
            return

        grounding_result = final_state.get("grounding_result")
        await backend_client.set_run_result(
            run_id,
            final_state["answer"] or "",
            final_state["citations"],
            grounding_valid=grounding_result["valid"] if grounding_result else None,
            grounding_unsupported_claims=(grounding_result["unsupported_claims"] if grounding_result else None),
            latency_ms=final_state.get("answer_latency_ms"),
            prompt_tokens=final_state.get("answer_prompt_tokens"),
            completion_tokens=final_state.get("answer_completion_tokens"),
            edit_proposal=final_state.get("edit_proposal"),
            unexplored_collection_ids=_unexplored(final_state),
            questions=final_state.get("questions"),
        )
        await backend_client.update_run_status(run_id, "completed")
        await backend_client.add_run_event(run_id, "run_completed", {"citation_count": len(final_state["citations"])})
        # Dedupe: replan_research can contribute the same prompt version id more than once
        # (one per replan pass) - the join table stores which versions this run used, not how
        # many times each one fired.
        prompt_usages = final_state.get("prompt_usages") or []
        if prompt_usages:
            await backend_client.add_prompt_usages(run_id, list(dict.fromkeys(prompt_usages)))
        # A question is no basis for a title, nor for a check: the conversation is titled once it has an answer.
        if final_state.get("questions"):
            return
        await _check_grounding(run_id, final_state)
        await _generate_conversation_title(
            final_state["conversation_id"],
            final_state["original_query"],
            final_state["answer"] or "",
        )


async def _check_grounding(run_id: str, final_state: dict[str, Any]) -> None:
    """The check of the answer's claims, made once the run is completed - the user is not waiting for it - and only
    for an answer that was hard to write (several sources, a comparison). Best-effort, like the title: its verdict is
    recorded on the run, and it never turns a completed run into a failed one."""
    if not final_state.get("needs_grounding") or final_state.get("edit_proposal"):
        return
    try:
        result = await ground_check(final_state)
        if result is not None:
            await backend_client.set_run_grounding(run_id, result["valid"], result["unsupported_claims"])
    except Exception:
        logger.exception(f"Failed to check the grounding of run {run_id}")


def _unexplored(final_state: dict[str, Any]) -> list[str]:
    """Deduplicated across research tasks, and only collections still in this run's accessible set -
    the next "go further" starts from these, and they come back through the backend as is."""
    accessible_ids = {str(vdb["id"]) for vdb in final_state.get("accessible_vdbs") or []}
    return [vdb_id for vdb_id in dict.fromkeys(final_state.get("unexplored_vdb_ids") or []) if vdb_id in accessible_ids]


agent_service = AgentService()
