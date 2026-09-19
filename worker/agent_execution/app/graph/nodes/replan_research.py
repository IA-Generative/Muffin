from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.state import AgentState, ResearchTask

_BASE_SYSTEM_PROMPT = (
    "Coverage of a research query was judged insufficient. Given what's missing, produce only the new "
    "research tasks needed to fill those specific gaps - do not repeat searches already covered. Respond "
    'only with a JSON array of objects: {{"query": "...", "intent": "..." or null, "tool": {tool_names}}}.'
)

# Only ever offered when the run opted in (chat composer toggle, off by default - see
# AgentState.web_search_enabled) - this is precisely the "accessible knowledge bases turned out
# insufficient" case the web_search tool exists for (§ issue: "quand proposer cet outil").
_WEB_SEARCH_NOTE = (
    ' Use "web_search" for a gap the user\'s own knowledge bases already failed to cover - never '
    "for a gap that just needs a different search phrasing within them."
)


def _valid_tools(web_search_enabled: bool) -> frozenset[str]:
    return frozenset({"search", "web_search"}) if web_search_enabled else frozenset({"search"})


def _system_prompt(web_search_enabled: bool) -> str:
    tool_names = '"search", "web_search"' if web_search_enabled else '"search"'
    prompt = _BASE_SYSTEM_PROMPT.format(tool_names=tool_names)
    return prompt + (_WEB_SEARCH_NOTE if web_search_enabled else "")


def replan_research(state: AgentState) -> dict[str, Any]:
    """Targeted replan (§19): only the missing_information from evaluate_coverage turns into new
    tasks - the tasks that already completed are left untouched, never re-run from scratch."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    next_version = state["plan_version"] + 1
    missing = state["coverage_result"]["missing_information"]
    web_search_enabled = state["web_search_enabled"]
    set_activity(run_id, "replan_research", "Refining the research plan")
    emit(run_id, "replan_started", {"missing_information": missing, "plan_version": next_version})

    model = state["chat_model"]
    if model is None or not missing:
        new_queries = [{"query": gap, "intent": None, "tool": "search"} for gap in missing] or [
            {"query": state["contextualized_query"], "intent": None, "tool": "search"}
        ]
    else:
        new_queries = json_chat(
            model,
            _system_prompt(web_search_enabled),
            f"Original query: {state['contextualized_query']}\n\nMissing information: {missing}",
            fallback=[{"query": gap, "intent": None, "tool": "search"} for gap in missing],
        )
        if not isinstance(new_queries, list) or not new_queries:
            new_queries = [{"query": gap, "intent": None, "tool": "search"} for gap in missing]

    valid_tools = _valid_tools(web_search_enabled)
    new_tasks = [
        ResearchTask(
            id=f"replan-{next_version}-{i}",
            query=str(item.get("query", missing[i] if i < len(missing) else state["contextualized_query"])),
            intent=item.get("intent"),
            # Second, independent gate (see decompose_query._sanitize) against "web_search"
            # reaching a task when the run never opted in.
            tool=item.get("tool") if item.get("tool") in valid_tools else "search",
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
