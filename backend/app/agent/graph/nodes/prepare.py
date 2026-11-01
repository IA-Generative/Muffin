from typing import Any

from app.agent.backend_client import backend_client
from app.agent.graph.services.authoring import CREATE_VERBS, EDIT_VERBS
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.scope import within_pinned
from app.agent.graph.services.tool_guide import CALL_TOOL
from app.agent.graph.services.vdb_router import VECTOR_PREFILTER_THRESHOLD, vector_prefilter
from app.agent.graph.state import AgentState


async def _catalogue(state: AgentState, accessible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The collections the plan is shown. All of them when there are few; otherwise the ones whose description is the
    closest to the question (a vector search, no model), and always the ones the user attached."""
    if len(accessible) <= VECTOR_PREFILTER_THRESHOLD:
        return accessible
    close = await vector_prefilter(state["original_query"], accessible)
    pinned = set(state["pinned_vdb_ids"])
    shown = {str(vdb["id"]) for vdb in close}
    return close + [vdb for vdb in accessible if str(vdb["id"]) in pinned and str(vdb["id"]) not in shown]


async def prepare(state: AgentState) -> dict[str, Any]:
    """The first half of what the plan needs, and the part that reads no text: the collections the person may reach,
    computed backend-side from the authenticated user alone, and nothing later may grow past them (§4/§12). It runs
    beside the guardrails on the input (#516); `prepare_request` is the second half, which reads the request."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}

    await set_activity(run_id, "prepare", "Starting the research")
    await emit(run_id, "run_started", {"query": state["original_query"]})
    await emit(run_id, "vdb_discovery_started")
    accessible = await backend_client.list_accessible_collections(state["user_id"], state["user_groups"])
    if state.get("scope_locked"):
        # An assistant's collections are the only ones searched: nothing past them is shown to the plan, so nothing
        # later can reach it (#514).
        consulted = [
            cid for assistant in state.get("consultable_assistants") or [] for cid in assistant["collection_ids"]
        ]
        accessible = within_pinned([*state["pinned_vdb_ids"], *consulted], accessible)
    await emit(run_id, "vdb_discovery_completed", {"accessible_count": len(accessible)})
    return {"accessible_vdbs": accessible}


async def prepare_request(state: AgentState) -> dict[str, Any]:
    """What the plan needs from the request, without a model: the collections to show it, what the person may edit or
    add a document to (only loaded when the message looks like such a request), and the tools they may use. It waits
    for the guardrails on the input (#516) and reads the request as they left it - masked when they masked it - and
    does nothing at all when they stopped it: no embedding of the text, no call for the tools."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}
    if (state.get("guardrail") or {}).get("outcome") == "block":
        return {}

    accessible = state["accessible_vdbs"]
    query = state["original_query"]
    can_plan = state["chat_model"] is not None
    edit_candidates = (
        (await backend_client.list_editable_documents(run_id)) if can_plan and EDIT_VERBS.search(query) else []
    )
    create_candidates = (
        (await backend_client.list_editable_collections(run_id)) if can_plan and CREATE_VERBS.search(query) else []
    )
    # The tools the person may use, unless this assistant turns them off: one call to the backend, made once per run and
    # only for a run that has a model to choose among them (#343).
    tools = (
        await backend_client.tool_definitions(run_id)
        if can_plan and CALL_TOOL not in (state.get("disabled_tools") or [])
        else []
    )
    return {
        "available_tools": tools,
        "catalogue": (await _catalogue(state, accessible)),
        "edit_candidates": edit_candidates,
        "create_candidates": create_candidates,
        "execution_status": "running",
    }
