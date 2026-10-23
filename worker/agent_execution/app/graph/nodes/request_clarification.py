from typing import Any

from app.ask_user import free_text_question, render_questions, sanitize_questions
from app.config import settings
from app.graph.services.events import emit, set_activity
from app.graph.state import AgentState

_DEFAULT_QUESTION = "Could you clarify your request?"


def _questions(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """What to ask: the model's questions with options when it gave valid ones, otherwise its single
    free-text question (a prompt that predates the options, a model that gave none)."""
    questions = sanitize_questions(analysis.get("questions"))
    if questions:
        return questions
    return [free_text_question(analysis.get("clarification_question") or _DEFAULT_QUESTION)]


def request_clarification(state: AgentState) -> dict[str, Any]:
    """The request is ambiguous (§31): the run ends on the question(s) rather than waiting for an answer (#344).

    They are kept with the assistant's message - the thread is the state, not a task that waits - and the
    user's answer arrives as the next message of the conversation, which analyze_query reads with the history.
    Nobody to ask (a run started by a program), or the assistant already asked too many times in a row: the
    run carries on instead, and states the assumptions it makes."""
    run_id = state["run_id"]
    analysis = state["query_analysis"]
    if not state.get("interactive", True) or state.get("question_rounds", 0) >= settings.MAX_QUESTION_ROUNDS:
        return {"query_analysis": {**analysis, "ambiguous": False}, "must_assume": True}

    questions = _questions(analysis)
    text = render_questions(questions)
    set_activity(run_id, "request_clarification", "Asking for a precision")
    # Same event as before (its `question` is the text of what is asked), with the questions themselves.
    emit(run_id, "clarification_requested", {"question": text, "questions": questions})
    return {"answer": text, "citations": [], "questions": questions}
