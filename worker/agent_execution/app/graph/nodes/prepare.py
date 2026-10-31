from typing import Any

from app.backend_client import backend_client
from app.graph.services.authoring import CREATE_VERBS, EDIT_VERBS
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.vdb_router import VECTOR_PREFILTER_THRESHOLD, vector_prefilter
from app.graph.state import AgentState


def _catalogue(state: AgentState, accessible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The collections the plan is shown. All of them when there are few; otherwise the ones whose description is the
    closest to the question (a vector search, no model), and always the ones the user attached."""
    if len(accessible) <= VECTOR_PREFILTER_THRESHOLD:
        return accessible
    close = vector_prefilter(state["original_query"], accessible)
    pinned = set(state["pinned_vdb_ids"])
    shown = {str(vdb["id"]) for vdb in close}
    return close + [vdb for vdb in accessible if str(vdb["id"]) in pinned and str(vdb["id"]) not in shown]


def prepare(state: AgentState) -> dict[str, Any]:
    """Everything the plan needs, without a model. The accessible collections are computed backend-side from the
    authenticated user alone, and nothing later may grow past them (§4/§12). What the user may edit, or add a document
    to, is only loaded when the message looks like such a request."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "prepare", "Starting the research")
    emit(run_id, "run_started", {"query": state["original_query"]})
    emit(run_id, "vdb_discovery_started")
    accessible = backend_client.list_accessible_collections(state["user_id"], state["user_groups"])
    emit(run_id, "vdb_discovery_completed", {"accessible_count": len(accessible)})

    query = state["original_query"]
    can_plan = state["chat_model"] is not None
    edit_candidates = backend_client.list_editable_documents(run_id) if can_plan and EDIT_VERBS.search(query) else []
    create_candidates = (
        backend_client.list_editable_collections(run_id) if can_plan and CREATE_VERBS.search(query) else []
    )
    return {
        "accessible_vdbs": accessible,
        "catalogue": _catalogue(state, accessible),
        "edit_candidates": edit_candidates,
        "create_candidates": create_candidates,
        "execution_status": "running",
    }
