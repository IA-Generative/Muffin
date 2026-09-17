from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import default_model, json_chat
from app.graph.state import AgentState, GroundingResult

_SYSTEM_PROMPT = (
    "Check whether every important factual claim in the answer is supported by the given evidence "
    'excerpts. Respond only with a JSON object: {"valid": bool, "unsupported_claims": [array of short '
    "strings quoting or paraphrasing each unsupported claim, empty if valid]}."
)


def validate_grounding(state: AgentState) -> dict[str, Any]:
    """Claim-by-claim check after generation (§23), not just the structural "citations exist"
    check generate_answer already enforces - this catches an answer that cites real excerpts but
    still asserts something they don't actually say."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "validate_grounding", "Double-checking the answer")
    emit(run_id, "grounding_validation_started")
    answer = state["answer"] or ""
    excerpts = state["answer_context"]["excerpts"] if state.get("answer_context") else []

    if not excerpts:
        # No evidence means generate_answer already refused to answer substantively - nothing to
        # ground-check against, and nothing further to research either.
        result = GroundingResult(valid=True, unsupported_claims=[])
    else:
        model = default_model()
        if model is None:
            result = GroundingResult(valid=True, unsupported_claims=[])
        else:
            evidence_block = "\n\n".join(f"[{e['id']}] {e['content'][:500]}" for e in excerpts)
            raw = json_chat(
                model,
                _SYSTEM_PROMPT,
                f"Answer:\n{answer}\n\nEvidence:\n{evidence_block}",
                fallback={"valid": True, "unsupported_claims": []},
            )
            if not isinstance(raw, dict) or "valid" not in raw:
                raw = {"valid": True, "unsupported_claims": []}
            result = GroundingResult(valid=bool(raw["valid"]), unsupported_claims=raw.get("unsupported_claims", []))

    emit(run_id, "grounding_validation_completed", dict(result))
    return {"grounding_result": result}
