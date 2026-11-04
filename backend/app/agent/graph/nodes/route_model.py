from typing import Any

from loguru import logger

from app.agent.backend_client import backend_client
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.llm import json_chat
from app.agent.graph.services.prompts import get_prompt
from app.agent.graph.state import AgentState

_COMPLEXITIES = ("simple", "moderate", "complex")
_INTENTS = ("chitchat", "lookup", "summary", "analysis", "reasoning", "code", "data", "writing", "other")
# How much of the conversation the classifier reads: what the request refers back to, no more.
_HISTORY_MESSAGES = 4
_MESSAGE_CHARS = 600

_SYSTEM_PROMPT = """You rate how demanding a request is, to pick the cheapest language model that can handle it.

Answer with ONE JSON object and nothing else:
{{"level": <integer 0-100>, "complexity": "simple" | "moderate" | "complex", "intent": "<intent>", \
"preferred_model": "<model id or null>", "reason": "<one short sentence>"}}

- level: how hard the task is. 0-20 a greeting or a trivial lookup, 20-40 a simple question about a document, \
40-60 a summary or a comparison, 60-80 multi-step analysis, reasoning over several sources, tables or code, \
80-100 the hardest tasks (long, ambiguous, technical, demanding precision).
- complexity: how much work the answer takes (steps, sources to combine, length).
- intent: one of {intents}.
- preferred_model: only if, among the models below, one is described as especially good at this kind of request. \
Otherwise null. Never invent an id.

Models available (id, score of the hardest task it handles well, what it does well):
{models}"""


def _models_listing(candidates: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {c['model']} (score {c['score']}){': ' + c['description'] if c.get('description') else ''}"
        for c in candidates
    )


def _user_content(state: AgentState) -> str:
    history = [m for m in state["messages"][:-1] if m.get("role") in ("user", "assistant")][-_HISTORY_MESSAGES:]
    lines = [f"{m['role']}: {str(m['content'])[:_MESSAGE_CHARS]}" for m in history]
    current = str(state["original_query"])[: _MESSAGE_CHARS * 3]
    facts = []
    if state.get("images"):
        facts.append(f"{len(state['images'])} image(s) attached")
    if state.get("web_search_enabled"):
        facts.append("web search on")
    return (
        ("Conversation so far:\n" + "\n".join(lines) + "\n\n" if lines else "")
        + f"Request to rate:\n{current}"
        + (f"\n\n({', '.join(facts)})" if facts else "")
    )


def _level(value: Any) -> int | None:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


def classify(raw: Any, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The classifier's answer as the choice reads it, or None if it is not one: whatever the model wrote, the level
    is a number of 0 to 100 and the other fields are among the known words."""
    if not isinstance(raw, dict):
        return None
    level = _level(raw.get("level"))
    if level is None:
        return None
    complexity = raw.get("complexity")
    intent = raw.get("intent")
    preferred = raw.get("preferred_model")
    return {
        "level": level,
        "complexity": complexity if complexity in _COMPLEXITIES else "moderate",
        "intent": intent if intent in _INTENTS else "other",
        "preferred_model": preferred if preferred in {c["model"] for c in candidates} else None,
        "reason": str(raw.get("reason") or "")[:300],
    }


def choose(candidates: list[dict[str, Any]], classification: dict[str, Any], *, needs_vision: bool) -> dict[str, Any]:
    """The cheapest model whose score covers the level (the one the classifier prefers, if it covers it too). When no
    model covers it, the best there is. With images, models that read them come first - the answer reads them with
    another anyway if none does (#512)."""
    pool = [c for c in candidates if c["vision"]] if needs_vision else []
    pool = pool or candidates
    eligible = [c for c in pool if c["score"] >= classification["level"]]
    preferred = next((c for c in eligible if c["model"] == classification["preferred_model"]), None)
    if preferred is not None:
        return preferred
    if eligible:
        return min(eligible, key=lambda c: (c["score"], c["model"]))
    return max(pool, key=lambda c: (c["score"], c["model"]))


def _classifier_model(candidates: list[dict[str, Any]], configured: str | None) -> str:
    # `candidates` is sorted cheapest first by the backend.
    return configured or candidates[0]["model"]


async def route_model(state: AgentState) -> dict[str, Any]:
    """Auto mode: when the person did not pick a model, one short call rates the request (level, complexity, intent) and
    the model whose score covers it is the one every call of this run uses. A model picked by hand is used as it is,
    and anything that goes wrong - no model rated, a classifier that fails - leaves the default model: auto mode never
    makes a run fail."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}
    if state.get("requested_model"):
        return {"routing": {"mode": "manual", "model": state["requested_model"]}}

    try:
        offer = await backend_client.get_auto_candidates()
    except Exception:
        logger.exception("Could not read the models auto mode chooses from, keeping the default model")
        return {}
    candidates = offer["candidates"]
    if not candidates:
        return {}

    await set_activity(run_id, "route_model", "Choosing the model")
    needs_vision = bool(state.get("images"))
    classification = None
    if len(candidates) > 1:
        template, _version = await get_prompt("route_model", fallback=_SYSTEM_PROMPT)
        system_prompt = template.replace("{intents}", ", ".join(_INTENTS)).replace(
            "{models}", _models_listing(candidates)
        )
        raw = await json_chat(
            _classifier_model(candidates, offer.get("classifier_model")),
            system_prompt,
            _user_content(state),
            fallback=None,
        )
        classification = classify(raw, candidates)

    if classification is None:
        # One model to pick from, or a classifier that failed: the default model, as before auto mode existed.
        if len(candidates) > 1:
            return {}
        chosen, classification = candidates[0], {"level": None, "complexity": None, "intent": None, "reason": ""}
    else:
        chosen = choose(candidates, classification, needs_vision=needs_vision)

    routing = {
        "mode": "auto",
        "model": chosen["model"],
        "level": classification["level"],
        "complexity": classification["complexity"],
        "intent": classification["intent"],
        "reason": classification["reason"],
    }
    await backend_client.update_run_state(run_id, routing=routing)
    await emit(run_id, "model_routed", routing)
    return {"chat_model": chosen["model"], "routing": routing}
