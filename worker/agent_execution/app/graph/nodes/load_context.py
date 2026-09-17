from typing import Any

from app.graph.services.events import emit, set_activity
from app.graph.state import AgentState


def load_context(state: AgentState) -> dict[str, Any]:
    """Entry node - the run's identity/messages already come from the Celery task's initial
    state (itself read from the `Run` row by AgentService), never from the query text or the
    LLM. This node's only job is to mark the run as started; it does not re-derive identity."""
    set_activity(state["run_id"], "load_context", "Starting the research")
    emit(state["run_id"], "run_started", {"query": state["original_query"]})
    return {"execution_status": "running"}
