from typing import Any

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.evidence import normalize_results
from app.graph.services.vdb_router import select_relevant_vdbs
from app.graph.state import AgentState, ResearchTask

_MAX_CLAIMS_RESEARCHED = 3


def targeted_research(state: AgentState) -> dict[str, Any]:
    """Second, narrower research loop triggered by a grounding failure (§24) - searches only for
    the specific unsupported claims, not a full replan. Kept as one controller node rather than
    fanning out through `research_task` again: a handful of grounding gaps don't need a DAG."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    claims = state["grounding_result"]["unsupported_claims"][:_MAX_CLAIMS_RESEARCHED]
    count = state["grounding_research_count"] + 1
    set_activity(run_id, "targeted_research", "Looking for additional support for the answer")
    emit(run_id, "grounding_research_started", {"unsupported_claims": claims, "attempt": count})

    model = state["chat_model"]
    new_tasks: list[ResearchTask] = []
    evidence = []
    for i, claim in enumerate(claims):
        task_id = f"grounding-{count}-{i}"
        selected_vdbs = select_relevant_vdbs(claim, state["accessible_vdbs"], model, state["pinned_vdb_ids"])
        results = (
            backend_client.search([str(v["id"]) for v in selected_vdbs], claim, settings.SEARCH_RESULTS_PER_QUERY)
            if selected_vdbs
            else []
        )
        # Always "search" here (unlike research_task, there's no other tool in the grounding
        # loop) - tagged the same way as research_task's central stamp, see there for why.
        evidence.extend(
            {**e, "metadata": {**e["metadata"], "tool": "search"}} for e in normalize_results(task_id, claim, results)
        )
        new_tasks.append(
            ResearchTask(
                id=task_id,
                query=claim,
                intent="grounding_gap",
                tool="search",
                dependencies=[],
                status="completed",
                candidate_vdbs=[],
                selected_vdbs=[str(v["id"]) for v in selected_vdbs],
                search_queries=[claim],
                results=results,
                error=None,
            )
        )

    emit(run_id, "grounding_research_completed", {"evidence_count": len(evidence)})
    return {
        "research_tasks": new_tasks,
        "completed_task_ids": [t["id"] for t in new_tasks],
        "evidence": evidence,
        "grounding_research_count": count,
    }
