from typing import Any

from langgraph.types import interrupt

from app.graph.services.events import emit, set_activity
from app.graph.state import AgentState


def request_clarification(state: AgentState) -> dict[str, Any]:
    """HITL pause (§31) using LangGraph's native interrupt - the graph halts here, the run's
    status is reported as waiting, and resuming (Command(resume=...)) re-enters this node with
    the user's answer instead of going through a bespoke pause/resume mechanism."""
    run_id = state["run_id"]
    question = state["query_analysis"].get("clarification_question") or "Could you clarify your request?"
    set_activity(run_id, "request_clarification", "Waiting for your clarification")
    emit(run_id, "clarification_requested", {"question": question})

    answer = interrupt({"question": question})

    emit(run_id, "clarification_received", {"answer": answer})
    return {
        "messages": state["messages"] + [{"role": "user", "content": answer}],
        "query_analysis": {**state["query_analysis"], "ambiguous": False},
    }
