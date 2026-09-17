from typing import Any

from app.graph.services.events import emit, is_cancelled
from app.graph.state import AgentState

_MAX_EVIDENCE_FOR_ANSWER = 20


def build_answer_context(state: AgentState) -> dict[str, Any]:
    """Prepares only what generate_answer needs (§21) - the highest-relevance excerpts, ordered
    and capped, never the entire evidence pool dumped verbatim into the prompt."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    ordered = sorted(state["deduped_evidence"], key=lambda e: e["relevance_score"] or 0.0, reverse=True)
    selected = ordered[:_MAX_EVIDENCE_FOR_ANSWER]
    coverage = state.get("coverage_result")

    context = {
        "evidence_ids": [e["id"] for e in selected],
        "excerpts": [
            {
                "id": e["id"],
                "content": e["content"],
                "source": e["metadata"].get("document_name"),
                "vdb_id": e["vdb_id"],
            }
            for e in selected
        ],
        "coverage_insufficient": coverage["status"] == "insufficient" if coverage else False,
        "missing_information": coverage["missing_information"] if coverage else [],
    }
    emit(run_id, "answer_context_built", {"evidence_count": len(selected)})
    return {"answer_context": context}
