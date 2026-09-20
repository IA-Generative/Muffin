import re
from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.state import AgentState, ResearchTask, TaskTool

_BASE_TOOLS: tuple[str, ...] = (
    "search",
    "list_collections",
    "collection_summary",
    "list_documents",
    "page_content",
    "tabular_query",
    "time",
)

# Keywords (FR + EN) that strongly signal an analytical question - one that requires computing
# over data rows (aggregation, counting, averaging, sorting) rather than reading document text.
# When the query matches, decompose_query must NOT short-circuit to a plain "search" fallback:
# the LLM planner is the only one that can decide whether tabular_query is the right tool, and
# short-circuiting would silently force "search" and miss tabular data entirely.
_ANALYTICAL_KEYWORDS: tuple[str, ...] = (
    # French
    "moyen",
    "moyenne",
    "moyennes",
    "total",
    "totaux",
    "somme",
    "sommes",
    "nombre",
    "compte",
    "compter",
    "dénombr",
    "combien",
    "min",
    "max",
    "minimum",
    "maximum",
    "médiane",
    "mediane",
    "écart-type",
    "ecart-type",
    "variance",
    "pourcentage",
    "ratio",
    "proportion",
    "agrégat",
    "agregat",
    "classement",
    "classé",
    "classés",
    "trié",
    "triés",
    "top",
    "pire",
    "meilleur",
    "pire",
    "plus grand",
    "plus petit",
    "plus élevé",
    "plus bas",
    "supérieur à",
    "inférieur à",
    "par groupe",
    "groupé par",
    "regroup",
    "filtre",
    "filtrer",
    "distinct",
    "unique",
    # English
    "average",
    "mean",
    "sum",
    "count",
    "how many",
    "minimum",
    "maximum",
    "median",
    "standard deviation",
    "variance",
    "percentage",
    "ratio",
    "proportion",
    "aggregate",
    "ranking",
    "ranked",
    "sorted",
    "group by",
    "grouped by",
    "filter",
    "distinct",
    "unique",
)

# Pre-compiled regex: matches any analytical keyword as a whole word (case-insensitive).
_ANALYTICAL_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in _ANALYTICAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _looks_analytical(query: str) -> bool:
    """True when the query contains an aggregation/analytical keyword. Used to prevent the
    simple-search short-circuit from forcing 'search' on a question that should go through
    the LLM planner so it can pick 'tabular_query'."""
    return bool(_ANALYTICAL_RE.search(query))


_BASE_TOOL_GUIDE = (
    "Tool guide:\n"
    '- "search": look for information inside document content - the default for most questions.\n'
    '- "list_collections": the user asks how many knowledge bases/collections they have, or wants them listed.\n'
    '- "collection_summary": the user wants a summary/description of one specific collection.\n'
    '- "list_documents": the user asks how many documents are in a collection, or wants a document\'s summary.\n'
    '- "page_content": the user wants the text and/or screenshot of one specific page of one document.\n'
    '- "tabular_query": the user asks an analytical question about tabular data (CSV/XLSX/Parquet/JSON) - '
    "aggregations, counts, averages, sums, filters, sorting, grouping, min/max. Use this when the question "
    "requires computing over data rows rather than reading document text. This is the correct tool for ANY "
    'question involving: averages/means, totals/sums, counts ("how many"), min/max, medians, rankings, '
    'grouping, filtering, or comparisons across rows. Examples: "how many rows have X > 100?", '
    '"what is the average of column Y grouped by Z?", "show me the top 5 by revenue", '
    '"quel est le revenu moyen ?", "combien y a-t-il de déclarants ?". '
    "When in doubt between search and tabular_query for a question that involves numbers or "
    "aggregation, prefer tabular_query.\n"
    '- "time": the user asks about the current date/time, or references relative periods (today, this week, '
    "last month, etc.) to filter or compare documents/tasks. Always pick this tool when the query needs "
    "temporal context the LLM cannot infer alone.\n"
)

# Only ever appended when the run opted in (chat composer toggle, off by default - see
# AgentState.web_search_enabled) - the planner must never even be told this tool exists
# otherwise, since offering it is itself the opt-in the issue this ships for requires.
_WEB_SEARCH_TOOL_GUIDE = (
    '- "web_search": the accessible knowledge bases are insufficient, or the question is explicitly about '
    "something outside the user's own documents (current events, general knowledge). The query sent to this "
    "tool must stay the user's own question - never paste in excerpts from private documents.\n"
)


def _valid_tools(web_search_enabled: bool) -> frozenset[str]:
    tools = (*_BASE_TOOLS, "web_search") if web_search_enabled else _BASE_TOOLS
    return frozenset(tools)


def _system_prompt(web_search_enabled: bool) -> str:
    # Iterates _BASE_TOOLS directly (not _valid_tools' frozenset) so the listed order is
    # deterministic between calls - purely cosmetic (prompt readability), never load-bearing.
    tools = (*_BASE_TOOLS, "web_search") if web_search_enabled else _BASE_TOOLS
    tool_names = ", ".join(f'"{tool}"' for tool in tools)
    guide = _BASE_TOOL_GUIDE + (_WEB_SEARCH_TOOL_GUIDE if web_search_enabled else "")
    return (
        "Break the user's query into research tasks. Respond only with a JSON array of objects with keys: "
        '"id" (short slug, unique), "query" (the question this task answers), "intent" (short string or null), '
        f'"tool" (one of {tool_names}), '
        '"dependencies" (array of task ids this task needs completed first, e.g. a comparison task depends on '
        "the tasks covering each side of the comparison).\n\n"
        f"{guide}\n"
        "A simple query stays a single task. Independent tasks must have an empty dependencies array so they can "
        "run in parallel."
    )


def _fallback_task(query: str, tool: TaskTool = "search") -> list[dict[str, Any]]:
    return [
        {
            "id": "task-1",
            "query": query,
            "intent": None,
            "tool": tool,
            "dependencies": [],
        }
    ]


def _sanitize(raw: list[Any], original_query: str, web_search_enabled: bool) -> list[ResearchTask]:
    if not isinstance(raw, list) or not raw:
        raw = _fallback_task(original_query)

    valid_tools = _valid_tools(web_search_enabled)
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
        # Second, independent gate against "web_search" reaching a task when the run never
        # opted in - not just relying on the prompt never offering it (§ security).
        tool = item.get("tool") if item.get("tool") in valid_tools else "search"
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
    web_search_enabled = state["web_search_enabled"]

    is_simple_search = (
        analysis.get("intent") != "meta"
        and not analysis.get("requires_multiple_sources")
        and analysis.get("complexity") == "simple"
    )
    # When web search is opted in, never short-circuit to a plain "search" fallback - the LLM
    # planner is the only one that can decide whether this specific query actually needs the web
    # (vs. the user's own documents). Skipping it means a simple-looking query like "qui est le
    # président actuel ?" always falls back to "search" and the web_search tool is never picked,
    # even though the user explicitly toggled it on.
    #
    # Likewise, never short-circuit when the query looks analytical (averages, counts, sums, etc.):
    # the simple-search fallback forces "search", but an analytical question may need "tabular_query"
    # to run SQL over CSV/XLSX data. Only the LLM planner can make that call.
    if is_simple_search and not web_search_enabled and not _looks_analytical(query):
        tasks = _sanitize(_fallback_task(query), query, web_search_enabled)
    else:
        model = state["chat_model"]
        if model is None:
            tasks = _sanitize(_fallback_task(query), query, web_search_enabled)
        else:
            raw = json_chat(
                model,
                _system_prompt(web_search_enabled),
                f"Query: {query}\n\nAnalysis: {analysis}",
                fallback=_fallback_task(query),
            )
            tasks = _sanitize(raw, query, web_search_enabled)

    emit(
        run_id,
        "query_decomposition_completed",
        {"task_count": len(tasks), "task_ids": [t["id"] for t in tasks]},
    )
    return {"research_tasks": tasks}
