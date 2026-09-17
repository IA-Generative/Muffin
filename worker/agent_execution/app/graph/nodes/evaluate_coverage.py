from typing import Any

from app.graph.services.events import emit, is_cancelled
from app.graph.services.llm import default_model, json_chat
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

    emit(run_id, "coverage_evaluation_started")
    evidence = state["deduped_evidence"]

    if not evidence:
        coverage = CoverageResult(
            status="insufficient",
            missing_information=["no evidence retrieved yet"],
            reasoning="No search returned results.",
        )
    else:
        model = default_model()
        if model is None:
            coverage = CoverageResult(
                status="sufficient", missing_information=[], reasoning="No model available to judge."
            )
        else:
            excerpts = "\n\n".join(f"[{e['id']}] {e['content'][:500]}" for e in evidence)
            raw = json_chat(
                model,
                _SYSTEM_PROMPT,
                f"Original query: {state['original_query']}\n\nEvidence:\n{excerpts}",
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
