from typing import Any

from app.ask_user import GUIDANCE, free_text_question, render_questions, sanitize_questions
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.services.prompts import get_prompt
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "The documents searched so far do not contain enough to answer the user's question. Rather than searching "
    "again, ask the user what they meant, proposing the plausible interpretations as options (for instance the "
    "document, period, product or meaning they are most likely after, based on what the excerpts do contain). "
    f"{GUIDANCE} Respond only with a JSON object: "
    '{{"questions": [{{"question": "...", "header": "...", "multi_select": false, '
    '"options": [{{"label": "...", "description": "..."}}]}}]}}.'
)

_DEFAULT_QUESTION = "I could not find enough to answer. Could you tell me more precisely what you are looking for?"
_MAX_EXCERPTS = 8


def clarify_coverage(state: AgentState) -> dict[str, Any]:
    """Insufficient coverage no longer triggers another round of research: the run ends on questions asking
    the user what they meant, so a request the documents can't answer never loops. The reply arrives as the
    next message of the conversation, read by analyze_query with the history (#344).

    Without a model, or when it gives no usable question, a generic free-text question is asked instead."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "clarify_coverage", "Asking for a precision")
    missing = state["coverage_result"]["missing_information"]
    questions: list[dict[str, Any]] = []
    prompt_usages: list[str] = []

    model = state["chat_model"]
    if model is not None:
        system_prompt, prompt_version_id = get_prompt("clarify_coverage", fallback=_SYSTEM_PROMPT)
        if prompt_version_id:
            prompt_usages.append(prompt_version_id)
        evidence = state["deduped_evidence"][:_MAX_EXCERPTS]
        excerpts = "\n\n".join(f"- {e['content'][:300]}" for e in evidence) or "(nothing relevant found)"
        raw = json_chat(
            model,
            system_prompt,
            f"Question: {state['contextualized_query']}\n\nMissing information: {missing}\n\nExcerpts:\n{excerpts}",
            fallback={},
        )
        questions = sanitize_questions(raw.get("questions") if isinstance(raw, dict) else None)
    if not questions:
        questions = [free_text_question(_DEFAULT_QUESTION)]

    text = render_questions(questions)
    emit(run_id, "clarification_requested", {"question": text, "questions": questions})
    return {"answer": text, "citations": [], "questions": questions, "prompt_usages": prompt_usages}
