from typing import Any

from langgraph.types import Send

from app.agent.config import settings
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.state import AgentState, CoverageResult, ResearchTask

# What the gate judges: the tools whose answer is passages to cite. A lookup of the knowledge base itself (a count, a
# list, a page) is complete the moment it runs, and so is a SQL answer or the time.
_CONTENT_TOOLS = frozenset({"search", "web_search"})


def gate(state: AgentState) -> dict[str, Any]:
    """Whether what the research found is enough to write an answer - decided in code, from what was found, with no
    model (it replaces the model that judged the coverage and the one that judged whether the summaries sufficed).

    Enough: nothing to judge (a lookup of the knowledge base), or at least `GATE_MIN_EVIDENCE` passages of a content
    task above `GATE_MIN_SCORE`. Not enough is not a dead end: the answer says plainly what could not be established,
    and the search is first widened to every collection once if the plan had narrowed it."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "gate", "Checking whether the results are enough")
    emit(run_id, "coverage_evaluation_started")
    completed = set(state["completed_task_ids"])
    content_tasks = {t["id"] for t in state["research_tasks"] if t["id"] in completed and t["tool"] in _CONTENT_TOOLS}
    if not content_tasks:
        coverage = CoverageResult(status="sufficient", missing_information=[], reasoning="Nothing to search for.")
    else:
        good = [
            e
            for e in state["deduped_evidence"]
            if e["task_id"] in content_tasks and (e["relevance_score"] or 0.0) >= settings.GATE_MIN_SCORE
        ]
        if len(good) >= settings.GATE_MIN_EVIDENCE:
            coverage = CoverageResult(status="sufficient", missing_information=[], reasoning=f"{len(good)} passage(s).")
        else:
            coverage = CoverageResult(
                status="insufficient",
                missing_information=["no sufficiently relevant passage was found"],
                reasoning=f"{len(good)} passage(s).",
            )
    emit(run_id, "coverage_evaluation_completed", dict(coverage))
    return {"coverage_result": coverage}


def widen_search(state: AgentState) -> dict[str, Any]:
    """The plan had narrowed the search to some collections and they held too little: the content searches are made
    again in every accessible collection, once. A new task for each, so the first ones stay what they were."""
    run_id = state["run_id"]
    set_activity(run_id, "widen_search", "Searching all your knowledge bases")
    emit(run_id, "search_widened", {"from": state["scope_ids"]})
    searches = [t for t in state["research_tasks"] if t["tool"] in _CONTENT_TOOLS]
    wider = [
        ResearchTask(
            **{**task, "id": f"wide-{task['id']}", "status": "ready", "results": [], "selected_vdbs": [], "error": None}
        )
        for task in searches
    ]
    return {"scope_ids": [], "widened": True, "research_tasks": wider}


def fan_out(state: AgentState, tasks: list[ResearchTask]) -> list[Send]:
    return [
        Send(
            "research_task",
            {
                "run_id": state["run_id"],
                "user_id": state["user_id"],
                "accessible_vdbs": state["accessible_vdbs"],
                "scope_ids": state["scope_ids"],
                "task": task,
                "chat_model": state["chat_model"],
                "web_search_enabled": state["web_search_enabled"],
            },
        )
        for task in tasks
    ]
