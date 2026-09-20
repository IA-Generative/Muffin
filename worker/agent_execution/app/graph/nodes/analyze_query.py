from typing import Any

from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "Analyze the user's current question, in light of the conversation so far if any is given. Respond only "
    'with a JSON object with keys: "intent" (one of "lookup", "comparison", "synthesis", "meta"), "topics" '
    '(array of short strings), "requires_multiple_sources" (bool), "complexity" (one of "simple", "complex"), '
    '"ambiguous" (bool - true only if the question is still unclear once the conversation history is taken '
    'into account), "clarification_question" (string or null, only set if ambiguous is true), '
    '"standalone_query" (string - the current question rewritten to stand on its own, resolving any pronoun '
    'or reference back to something said earlier in the conversation, e.g. "elle"/"it" -> the thing it '
    "refers to; if the question is already self-contained or there is no conversation history, repeat it "
    "unchanged).\n\n"
    'Use "meta" when the query is about the knowledge bases themselves rather than their content - e.g. '
    "how many collections/documents the user has access to, a collection's or document's summary, or the "
    "content/screenshot of one specific page, rather than a document/policy question that content search "
    "should answer.\n\n"
    'IMPORTANT - be very conservative with "ambiguous": only set it to true if the question is truly '
    "unanswerable without more information. The user has already selected one or more collections to query "
    'against, so references like "le fichier", "les données", "the data", "the file" are NOT ambiguous - '
    "they refer to the selected collection(s). Questions about columns, rows, averages, counts, sums, or "
    "any analytical operation on tabular data are NOT ambiguous even if they don't name a specific file. "
    "When in doubt, set ambiguous to false - it is better to attempt an answer than to block the user with "
    "a clarification question."
)

_FALLBACK: dict[str, Any] = {
    "intent": "lookup",
    "topics": [],
    "requires_multiple_sources": False,
    "complexity": "simple",
    "ambiguous": False,
    "clarification_question": None,
    "standalone_query": None,
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

    # Everything but the current question itself, which is already the last entry appended by
    # AgentService.run() - without this, a follow-up like "elle parle de quoi ?" is judged in
    # total isolation and comes back ambiguous even though the answer is one turn away.
    history = state["messages"][:-1]
    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    user_content = (
        state["original_query"]
        if not history_text
        else f"Conversation so far:\n{history_text}\n\nCurrent question: {state['original_query']}"
    )

    model = state["chat_model"]
    if model is None:
        analysis = _FALLBACK
    else:
        analysis = json_chat(model, _SYSTEM_PROMPT, user_content, fallback=_FALLBACK)
        if not isinstance(analysis, dict) or "intent" not in analysis:
            analysis = _FALLBACK

    contextualized_query = analysis.get("standalone_query") or state["original_query"]
    emit(run_id, "query_analysis_completed", {"analysis": analysis})
    return {"query_analysis": analysis, "contextualized_query": contextualized_query}
