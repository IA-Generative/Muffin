from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import default_model, json_chat
from app.graph.state import AgentState, ResearchTask

_SYSTEM_PROMPT = (
    "Coverage of a research query was judged insufficient. Given what's missing, produce only the new "
    "research tasks needed to fill those specific gaps - do not repeat searches already covered. Respond "
    'only with a JSON array of objects: {"query": "...", "intent": "..." or null}.'
)


def replan_research(state: AgentState) -> dict[str, Any]:
    """Targeted replan (§19): only the missing_information from evaluate_coverage turns into new
    tasks - the tasks that already completed are left untouched, never re-run from scratch."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    next_version = state["plan_version"] + 1
    missing = state["coverage_result"]["missing_information"]
    set_activity(run_id, "replan_research", "Refining the research plan")
    emit(run_id, "replan_started", {"missing_information": missing, "plan_version": next_version})

    model = default_model()
    if model is None or not missing:
        new_queries = [{"query": gap, "intent": None} for gap in missing] or [
            {"query": state["original_query"], "intent": None}
        ]
    else:
        new_queries = json_chat(
            model,
            _SYSTEM_PROMPT,
            f"Original query: {state['original_query']}\n\nMissing information: {missing}",
            fallback=[{"query": gap, "intent": None} for gap in missing],
        )
        if not isinstance(new_queries, list) or not new_queries:
            new_queries = [{"query": gap, "intent": None} for gap in missing]

    new_tasks = [
        ResearchTask(
            id=f"replan-{next_version}-{i}",
            query=str(item.get("query", missing[i] if i < len(missing) else state["original_query"])),
            intent=item.get("intent"),
            tool="search",
            dependencies=[],
            status="pending",
            candidate_vdbs=[],
            selected_vdbs=[],
            search_queries=[],
            results=[],
            error=None,
        )
        for i, item in enumerate(new_queries)
        if isinstance(item, dict)
    ]

    emit(run_id, "replan_completed", {"new_task_ids": [t["id"] for t in new_tasks]})
    return {
        "research_tasks": new_tasks,
        "plan_version": next_version,
        "replan_count": state["replan_count"] + 1,
    }
