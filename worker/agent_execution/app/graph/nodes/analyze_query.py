from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import default_model, json_chat
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "Analyze the user's query before any research is done. Respond only with a JSON object with keys: "
    '"intent" (one of "lookup", "comparison", "synthesis", "meta"), "topics" (array of short strings), '
    '"requires_multiple_sources" (bool), "complexity" (one of "simple", "complex"), '
    '"ambiguous" (bool), "clarification_question" (string or null, only set if ambiguous is true). '
    'Use "meta" when the query is about the knowledge bases themselves rather than their content - e.g. '
    "how many collections/documents the user has access to, a collection's or document's summary, or the "
    "content/screenshot of one specific page, rather than a document/policy question that content search "
    "should answer."
)

_FALLBACK: dict[str, Any] = {
    "intent": "lookup",
    "topics": [],
    "requires_multiple_sources": False,
    "complexity": "simple",
    "ambiguous": False,
    "clarification_question": None,
}


def analyze_query(state: AgentState) -> dict[str, Any]:
    """Understands the request - intent, topics, whether it needs comparing/synthesizing several
    sources - without launching any search yet (§5). decompose_query consumes this to decide how
    many research tasks the query actually needs."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "analyze_query", "Analyzing your question")
    emit(run_id, "query_analysis_started", {"query": state["original_query"]})
    model = default_model()
    if model is None:
        analysis = _FALLBACK
    else:
        analysis = json_chat(model, _SYSTEM_PROMPT, state["original_query"], fallback=_FALLBACK)
        if not isinstance(analysis, dict) or "intent" not in analysis:
            analysis = _FALLBACK

    emit(run_id, "query_analysis_completed", {"analysis": analysis})
    return {"query_analysis": analysis}
