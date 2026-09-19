from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.state import AgentState

_MAX_EVIDENCE_FOR_ANSWER = 20


def build_answer_context(state: AgentState) -> dict[str, Any]:
    """Prepares only what generate_answer needs (§21) - the highest-relevance excerpts, ordered
    and capped, never the entire evidence pool dumped verbatim into the prompt."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "build_answer_context", "Preparing the answer")
    ordered = sorted(
        state["deduped_evidence"],
        key=lambda e: e["relevance_score"] or 0.0,
        reverse=True,
    )
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
                # Carried through for the frontend's sources panel (§ document vs tool cards):
                # "search"/"page_content" evidence links to a real document page, everything else
                # (list_collections, collection_summary, list_documents) is just input/output.
                "tool": e["metadata"].get("tool", "search"),
                # source_id is empty for QA/summary evidence (no specific document to cite) -
                # don't pass it as document_id, or link_citations would FK-violate.
                "document_id": e["source_id"] or None,
                "chunk_id": e["metadata"].get("chunk_id"),
                "page_number": e["metadata"].get("page_number"),
                # Only ever set on a web_search result (see research_task._web_result_evidence) -
                # what lets the frontend render a clickable external link instead of a
                # document/tool card (§ sources panel).
                "url": e["metadata"].get("url"),
                "query": e["retrieval_query"],
            }
            for e in selected
        ],
        "coverage_insufficient": (coverage["status"] == "insufficient" if coverage else False),
        "missing_information": coverage["missing_information"] if coverage else [],
    }
    emit(run_id, "answer_context_built", {"evidence_count": len(selected)})
    return {"answer_context": context}
