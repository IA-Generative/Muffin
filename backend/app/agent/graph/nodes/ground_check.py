"""The check of the answer's claims against the evidence, run once the answer is out (the run is already completed):
the user is not kept waiting for it, and its verdict is recorded on the run. One model call, made only for an
answer that was hard to write (several sources, a comparison) - never a reason to write the answer again."""

from typing import Any

from app.agent.graph.services.events import emit
from app.agent.graph.services.llm import json_chat
from app.agent.graph.services.prompts import get_prompt
from app.agent.graph.state import AgentState, GroundingResult
from app.agent.usage_context import set_usage

_SYSTEM_PROMPT = (
    "Check whether every important factual claim in the answer is supported by the given evidence "
    'excerpts. Respond only with a JSON object: {"valid": bool, "unsupported_claims": [array of short '
    "strings quoting or paraphrasing each unsupported claim, empty if valid]}.\n\n"
    "A claim that computes a count, sum, average, or other aggregate over items listed in the excerpts is "
    "supported as long as those underlying items are actually there - it does not need to appear as a "
    "pre-stated number in any single excerpt. Only flag it if the underlying items themselves are missing "
    "or the computation contradicts what's in the excerpts."
)

# In the code and not in the prompt (administrable, see get_prompt): the check of the citations is kept when the
# prompt is overridden (#402). A claim ends with the id of the excerpt that supports it, in brackets; where an excerpt
# has a cited passage it is given, and that passage is what the claim must rest on.
_CITATION_CHECK = (
    "\n\nAlso check the citations. Each claim of the answer should end with the id, in brackets, of the excerpt that "
    "supports it. Add to the JSON object: "
    '"miscited_claims": [{"claim": short text, "cited": id of the excerpt it cites, "supported_by": id of an excerpt '
    "that really supports it, or null}] for each claim that cites an excerpt which does not support it; "
    '"uncited_claims": [short text] for each claim that is supported by the excerpts but cites none. '
    "Use [] when there is none. A claim no excerpt supports goes in unsupported_claims only."
)

# What of an excerpt the check reads: the whole of a short one, and around the cited passage in a long one - not its
# first 500 characters, which made a claim supported further down look unsupported.
_EXCERPT_CHARS = 2000
_PASSAGE_MARGIN = 300


def _window(excerpt: dict[str, Any]) -> str:
    content = excerpt["content"]
    if len(content) <= _EXCERPT_CHARS:
        return content
    end = excerpt.get("quote_end")
    if end is None or end <= _EXCERPT_CHARS:
        return content[:_EXCERPT_CHARS] + " […]"
    start = max(0, (excerpt.get("quote_start") or 0) - _PASSAGE_MARGIN)
    return "[…] " + content[start : start + _EXCERPT_CHARS] + " […]"


def _evidence_line(excerpt: dict[str, Any]) -> str:
    passage = f" (cited passage: «{excerpt['quote']}»)" if excerpt.get("quote") else ""
    return f"[{excerpt['id']}]{passage} {_window(excerpt)}"


def _strings(value: Any, limit: int = 5) -> list[str]:
    return (
        [item.strip()[:300] for item in value if isinstance(item, str) and item.strip()][:limit]
        if isinstance(value, list)
        else []
    )


def _miscited(value: Any, valid_ids: set[str], limit: int = 5) -> list[dict[str, Any]]:
    """The claims cited with an excerpt that does not support them, for the ones whose cited id is really an excerpt."""
    if not isinstance(value, list):
        return []
    found = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str) or item.get("cited") not in valid_ids:
            continue
        better = item.get("supported_by")
        found.append(
            {
                "claim": item["claim"].strip()[:300],
                "cited": item["cited"],
                "supported_by": better if better in valid_ids else None,
            }
        )
    return found[:limit]


async def ground_check(state: AgentState) -> GroundingResult | None:
    """Claim-by-claim check after generation (§23), not just the structural "citations exist" check generate_answer
    already enforces: it catches an answer that cites real excerpts but still asserts something they don't say, and
    (#402) claims that cite an excerpt which does not support them or cite none. None when there is nothing to check."""
    run_id = state["run_id"]
    answer = state["answer"] or ""
    excerpts = state["answer_context"]["excerpts"] if state.get("answer_context") else []
    model = state["chat_model"]
    if not answer or not excerpts or model is None:
        return None

    # Made after the graph, so no node named the step: the call is the check's, not the answer's.
    set_usage(run_id=run_id, step="ground_check")
    await emit(run_id, "grounding_validation_started")
    valid_ids = {e["id"] for e in excerpts}
    # A citation whose passage the excerpt does not have: found without a model, whatever the check says.
    unverified = [c["evidence_id"] for c in state.get("citations") or [] if c.get("cited") and not c.get("quote")]
    evidence_block = "\n\n".join(_evidence_line(e) for e in excerpts)
    system_prompt, _prompt_version_id = await get_prompt("validate_grounding", fallback=_SYSTEM_PROMPT)
    raw = await json_chat(
        model,
        system_prompt + _CITATION_CHECK,
        f"Answer:\n{answer}\n\nEvidence:\n{evidence_block}",
        fallback={"valid": True, "unsupported_claims": []},
    )
    if not isinstance(raw, dict) or "valid" not in raw:
        raw = {"valid": True, "unsupported_claims": []}
    result = GroundingResult(
        valid=bool(raw["valid"]),
        unsupported_claims=raw.get("unsupported_claims", []),
        miscited_claims=_miscited(raw.get("miscited_claims"), valid_ids),
        uncited_claims=_strings(raw.get("uncited_claims")),
    )
    result["unverified_citations"] = unverified
    await emit(run_id, "grounding_validation_completed", dict(result))
    return result
