from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.state import AgentState


def rewrite_citations(state: AgentState) -> dict[str, Any]:
    """Prepares writing the answer again with its citations put right (#402): the claims that cite an excerpt which
    does not support them, or cite none although the excerpts did, are handed to generate_answer. Once - the answer
    that comes back stands, and is not checked a second time."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    grounding = state["grounding_result"] or {}
    claims = [
        f"{item['claim']} (cited {item['cited']}"
        + (f", supported by {item['supported_by']}" if item.get("supported_by") else "")
        + ")"
        for item in grounding.get("miscited_claims", [])
    ] + [f"{claim} (cites nothing)" for claim in grounding.get("uncited_claims", [])]
    set_activity(run_id, "rewrite_citations", "Attaching the answer to its sources")
    emit(run_id, "citation_rewrite_started", {"claims": claims})
    return {"citation_feedback": claims, "citation_rewrites": state.get("citation_rewrites", 0) + 1}
