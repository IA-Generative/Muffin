from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import default_model, json_chat
from app.graph.state import AgentState, ResearchTask, TaskTool

_VALID_TOOLS: frozenset[str] = frozenset(
    {"search", "list_collections", "collection_summary", "list_documents", "page_content"}
)

_SYSTEM_PROMPT = (
    "Break the user's query into research tasks. Respond only with a JSON array of objects with keys: "
    '"id" (short slug, unique), "query" (the question this task answers), "intent" (short string or null), '
    '"tool" (one of "search", "list_collections", "collection_summary", "list_documents", "page_content"), '
    '"dependencies" (array of task ids this task needs completed first, e.g. a comparison task depends on '
    "the tasks covering each side of the comparison).\n\n"
    "Tool guide:\n"
    '- "search": look for information inside document content - the default for most questions.\n'
    '- "list_collections": the user asks how many knowledge bases/collections they have, or wants them listed.\n'
    '- "collection_summary": the user wants a summary/description of one specific collection.\n'
    '- "list_documents": the user asks how many documents are in a collection, or wants a document\'s summary.\n'
    '- "page_content": the user wants the text and/or screenshot of one specific page of one document.\n\n'
    "A simple query stays a single task. Independent tasks must have an empty dependencies array so they can "
    "run in parallel."
)


def _fallback_task(query: str, tool: TaskTool = "search") -> list[dict[str, Any]]:
    return [{"id": "task-1", "query": query, "intent": None, "tool": tool, "dependencies": []}]


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
        tool = item.get("tool") if item.get("tool") in _VALID_TOOLS else "search"
        tasks.append(
            ResearchTask(
                id=task_id,
                query=str(item["query"]),
                intent=item.get("intent"),
                tool=tool,
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
            tool="search",
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
    a simple, single-source, content-search analysis short-circuits to a single search task
    without spending an LLM call. A "meta" query (about the knowledge bases themselves - counts,
    summaries, page content) always goes through the LLM so the right tool gets picked (§ meta-
    query tools)."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "decompose_query", "Breaking down your question")
    emit(run_id, "query_decomposition_started")
    analysis = state["query_analysis"]
    query = state["contextualized_query"]

    is_simple_search = (
        analysis.get("intent") != "meta"
        and not analysis.get("requires_multiple_sources")
        and analysis.get("complexity") == "simple"
    )
    if is_simple_search:
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
