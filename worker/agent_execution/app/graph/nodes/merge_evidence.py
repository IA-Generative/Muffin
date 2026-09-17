from typing import Any

from app.graph.services.events import emit, is_cancelled
from app.graph.state import AgentState, Evidence


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    """The fan-in reducer (operator.add on `evidence`) just concatenates every branch's output -
    dedupe here by source rather than in the reducer, since a replan may legitimately re-search
    a source another task already found (§16)."""
    seen: set[tuple[str, str]] = set()
    deduped = []
    for item in evidence:
        key = (item["vdb_id"], item["source_id"] + item["content"][:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def merge_evidence(state: AgentState) -> dict[str, Any]:
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    deduped = _dedupe(state["evidence"])
    emit(
        run_id,
        "evidence_updated",
        {
            "evidence_count": len(deduped),
            "completed_tasks": len(state["completed_task_ids"]),
            "failed_tasks": len(state["failed_task_ids"]),
        },
    )
    return {"deduped_evidence": deduped}
