from typing import Any

from app.ask_user import render_questions, sanitize_questions
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.vdb_router import collection_path, routing_confidence
from app.graph.state import AgentState

_QUESTION = "Dans quelle collection dois-je chercher ?"
_HEADER = "Collection"


def _questions(ranked: list[tuple[dict[str, Any], float]], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One multiple-choice question: the collections the question lands in, best first, each with its
    description - several can apply."""
    options = [
        {"label": collection_path(vdb, by_id), "description": vdb.get("description") or ""}
        for vdb, _share in ranked[: settings.ROUTING_MAX_OPTIONS]
    ]
    return [{"question": _QUESTION, "header": _HEADER, "multi_select": True, "options": options}]


def route_collections(state: AgentState) -> dict[str, Any]:
    """Before searching, checks the question clearly lands in some collection (routing confidence).

    When nothing dominates, the run ends on a question proposing the closest collections rather than
    guessing among them; the user's reply arrives with the next message and is read with the history.
    Left alone: a question the user already scoped (collections attached, "go further"), a plan with
    no content search (the knowledge-base lookups), a run nobody can answer, and the message after one
    that already asked something - that one is never asked twice in a row. Every decision is reported
    as an event, so routing can be measured against the collections the answer ends up citing."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    accessible = state["accessible_vdbs"]
    searches = any(task.get("tool", "search") == "search" for task in state["research_tasks"])
    if (
        not searches
        or state["chat_model"] is None
        or len(accessible) < 2
        or state["pinned_vdb_ids"]
        or state["resume_from_vdb_ids"]
    ):
        return {}

    set_activity(run_id, "route_collections", "Checking where to search")
    confidence = routing_confidence(state["contextualized_query"], accessible)
    emit(
        run_id,
        "routing_confidence",
        {
            "decision": confidence.decision,
            "candidates": [
                {"id": str(vdb["id"]), "name": vdb["name"], "share": round(share, 3)}
                for vdb, share in confidence.ranked[: settings.ROUTING_MAX_OPTIONS]
            ],
        },
    )
    if confidence.decision != "flat" or not state.get("interactive", True) or state.get("question_rounds", 0) > 0:
        return {}
    if len(confidence.ranked) < 2:
        return {}

    questions = sanitize_questions(_questions(confidence.ranked, {str(v["id"]): v for v in accessible}))
    if not questions:
        return {}
    text = render_questions(questions)
    emit(run_id, "clarification_requested", {"question": text, "questions": questions})
    return {"answer": text, "citations": [], "questions": questions}
