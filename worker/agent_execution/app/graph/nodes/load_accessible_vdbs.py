from typing import Any

from app.backend_client import backend_client
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.state import AgentState


def load_accessible_vdbs(state: AgentState) -> dict[str, Any]:
    """Security barrier (§4/§12): the accessible set is computed backend-side from the
    authenticated user_id alone. Every later node that picks a VDB must intersect against
    this list - it must never grow past what is returned here.

    In this codebase a VDB *is* a Collection (§7 audit finding: there is no separate
    knowledge-base grouping above Collection today), so this simply reuses the existing
    ownership-scoped collections endpoint rather than inventing a parallel concept."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "load_accessible_vdbs", "Checking your accessible knowledge bases")
    emit(run_id, "vdb_discovery_started")
    accessible = backend_client.list_accessible_collections(state["user_id"], state["user_groups"])
    emit(run_id, "vdb_discovery_completed", {"accessible_count": len(accessible)})
    return {"accessible_vdbs": accessible}
