from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.state import AgentState, CoverageResult

_SYSTEM_PROMPT = (
    "Decide whether the given evidence excerpts are enough to answer the original query. Respond only with "
    'a JSON object: {"status": "sufficient" or "insufficient", "missing_information": [array of short '
    'strings describing what is missing, empty if sufficient], "reasoning": short string}.'
)


def evaluate_coverage(state: AgentState) -> dict[str, Any]:
    """Compares evidence against the query's actual requirements rather than a blanket "I have
    enough documents" (§17) - the missing_information list is what replan_research targets."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "evaluate_coverage", "Checking whether the results are enough")
    emit(run_id, "coverage_evaluation_started")
    evidence = state["deduped_evidence"]
    completed_ids = set(state["completed_task_ids"])
    completed_tasks = [t for t in state["research_tasks"] if t["id"] in completed_ids]
    is_meta_only = bool(completed_tasks) and all(t.get("tool", "search") != "search" for t in completed_tasks)

    if is_meta_only:
        # A knowledge-base lookup (list_collections, collection_summary, list_documents,
        # page_content) is complete the moment it runs - there's no "coverage" to judge, and a
        # replan would only ever produce a content search that can never answer it (§ meta-query
        # tools). An empty result is itself a valid answer (e.g. zero collections), not a miss.
        coverage = CoverageResult(status="sufficient", missing_information=[], reasoning="Knowledge-base lookup.")
    elif not evidence:
        coverage = CoverageResult(
            status="insufficient",
            missing_information=["no evidence retrieved yet"],
            reasoning="No search returned results.",
        )
    else:
        model = state["chat_model"]
        if model is None:
            coverage = CoverageResult(
                status="sufficient", missing_information=[], reasoning="No model available to judge."
            )
        else:
            excerpts = "\n\n".join(f"[{e['id']}] {e['content'][:500]}" for e in evidence)
            raw = json_chat(
                model,
                _SYSTEM_PROMPT,
                f"Original query: {state['contextualized_query']}\n\nEvidence:\n{excerpts}",
                fallback={"status": "sufficient", "missing_information": [], "reasoning": None},
            )
            if not isinstance(raw, dict) or raw.get("status") not in ("sufficient", "insufficient"):
                raw = {"status": "sufficient", "missing_information": [], "reasoning": None}
            coverage = CoverageResult(
                status=raw["status"],
                missing_information=raw.get("missing_information", []),
                reasoning=raw.get("reasoning"),
            )

    emit(run_id, "coverage_evaluation_completed", dict(coverage))
    return {"coverage_result": coverage}
