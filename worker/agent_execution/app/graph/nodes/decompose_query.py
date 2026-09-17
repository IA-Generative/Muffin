from typing import Any

from app.graph.services.events import emit, is_cancelled
from app.graph.services.llm import default_model, json_chat
from app.graph.state import AgentState, ResearchTask

_SYSTEM_PROMPT = (
    "Break the user's query into research tasks, one per distinct sub-topic that needs its own search. "
    "A simple query stays a single task. Respond only with a JSON array of objects with keys: "
    '"id" (short slug, unique), "query" (the search-oriented question for this task), '
    '"intent" (short string or null), "dependencies" (array of task ids this task needs the results of '
    "first, e.g. a comparison task depends on the tasks covering each side of the comparison). "
    "Independent tasks must have an empty dependencies array so they can run in parallel."
)


def _fallback_task(query: str) -> list[dict[str, Any]]:
    return [{"id": "task-1", "query": query, "intent": None, "dependencies": []}]


def _sanitize(raw: list[Any], original_query: str) -> list[ResearchTask]:
    if not isinstance(raw, list) or not raw:
        raw = _fallback_task(original_query)

    valid_ids = {str(item.get("id")) for item in raw if isinstance(item, dict) and item.get("id")}
    tasks: list[ResearchTask] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id") or not item.get("query"):
            continue
        task_id = str(item["id"])
        # Dependencies must reference tasks that actually exist in this same plan - never let
        # a malformed LLM response create a dangling edge the planner can't ever satisfy.
        dependencies = [
            str(dep) for dep in item.get("dependencies", []) if str(dep) in valid_ids and str(dep) != task_id
        ]
        tasks.append(
            ResearchTask(
                id=task_id,
                query=str(item["query"]),
                intent=item.get("intent"),
                dependencies=dependencies,
                status="pending",
                candidate_vdbs=[],
                selected_vdbs=[],
                search_queries=[],
                results=[],
                error=None,
            )
        )
    return tasks or [
        ResearchTask(
            id="task-1",
            query=original_query,
            intent=None,
            dependencies=[],
            status="pending",
            candidate_vdbs=[],
            selected_vdbs=[],
            search_queries=[],
            results=[],
            error=None,
        )
    ]


def decompose_query(state: AgentState) -> dict[str, Any]:
    """Turns the query into a DAG of ResearchTasks (§6/§7). Not every query needs decomposing -
    a simple lookup analysis short-circuits to a single task without spending an LLM call."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    emit(run_id, "query_decomposition_started")
    analysis = state["query_analysis"]
    query = state["original_query"]

    if not analysis.get("requires_multiple_sources") and analysis.get("complexity") == "simple":
        tasks = _sanitize(_fallback_task(query), query)
    else:
        model = default_model()
        if model is None:
            tasks = _sanitize(_fallback_task(query), query)
        else:
            raw = json_chat(
                model,
                _SYSTEM_PROMPT,
                f"Query: {query}\n\nAnalysis: {analysis}",
                fallback=_fallback_task(query),
            )
            tasks = _sanitize(raw, query)

    emit(run_id, "query_decomposition_completed", {"task_count": len(tasks), "task_ids": [t["id"] for t in tasks]})
    return {"research_tasks": tasks}
