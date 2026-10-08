import time
from typing import Any

from app.backend_client import EditRequestRefused, backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.state import AgentState

# Module attribute (not closed over) so tests run the wait loop without really sleeping.
_sleep = time.sleep


def _summary_lines(summary: str) -> list[str]:
    return [line.removeprefix("- ").strip() for line in summary.splitlines() if line.strip()]


def _answer(name: str, draft: dict[str, Any] | None, timed_out: bool) -> str:
    """What to tell the user. The proposal itself (preview, validate/adjust/refuse) is the card the
    chat shows next to this text, so the answer only says what the editing agent concluded."""
    if draft is None:
        return f"Je n'ai pas pu lancer la modification de « {name} »."
    if timed_out:
        return (
            f"L'agent d'édition travaille encore sur « {name} ». La proposition apparaîtra dans la carte "
            "ci-dessous dès qu'elle sera prête ; vous la retrouverez aussi sur la fiche du document."
        )
    if draft["status"] == "failed":
        return f"La modification de « {name} » n'a pas abouti : {draft.get('error') or 'erreur inconnue'}"
    if not draft["edited"]:
        explanation = draft.get("operations_summary") or "l'agent d'édition n'a rien modifié."
        return f"Je n'ai pas modifié « {name} » : {explanation}"
    changes = "\n".join(f"- {line}" for line in _summary_lines(draft.get("operations_summary", "")))
    return (
        f"J'ai préparé une modification de « {name} » :\n{changes}\n\n"
        "Elle n'est pas encore enregistrée : relisez la proposition dans la carte ci-dessous, puis "
        "validez-la, ajustez-la ou refusez-la."
    )


def delegate_edit(state: AgentState) -> dict[str, Any]:
    """Hands a change of a living document to the editing agent and waits for its verdict (#171).

    This agent never edits anything itself: it asks the backend to start the edit - which creates the
    draft, takes the document's lock and sends the job to the editing agent - then follows the draft
    until that agent is done, and reports what it concluded. Whether the user may edit the document
    is the backend's call (from the run's own identity), not this node's. Nothing is written to the
    collection: the user validates the proposal from the chat card."""
    run_id = state["run_id"]
    target = state["edit_target"] or {}

    # Nothing to delegate: several documents fit, and the user has to say which.
    if "clarification" in target:
        return {"answer": target["clarification"], "citations": [], "edit_proposal": None}

    name, document_id = target["document_name"], target["document_id"]
    proposal = {"collection_id": target["collection_id"], "document_id": document_id, "document_name": name}
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "delegate_edit", f"Asking the editing agent to change « {name} »")
    emit(run_id, "edit_delegated", {"document_id": document_id, "instruction": target["instruction"]})
    try:
        draft = backend_client.create_edit_request(run_id, document_id, target["instruction"])
    except EditRequestRefused as refusal:
        emit(run_id, "edit_refused", {"code": refusal.code, "message": refusal.message})
        # A proposal already waiting on this document is worth showing: that is where the user
        # should go next, so the card stays.
        return {
            "answer": refusal.message,
            "citations": [],
            "edit_proposal": proposal if refusal.code == "draft_exists" else None,
        }

    deadline = time.monotonic() + settings.EDIT_WAIT_SECONDS
    timed_out = False
    while draft["status"] == "pending":
        if time.monotonic() >= deadline:
            timed_out = True
            break
        _sleep(settings.EDIT_POLL_SECONDS)
        if is_cancelled(run_id):
            return {"cancelled": True}
        try:
            draft = backend_client.get_edit_request(run_id, document_id)
        except EditRequestRefused as refusal:
            # The draft is gone (refused from the UI, or it lapsed) while this run waited for it.
            emit(run_id, "edit_refused", {"code": refusal.code, "message": refusal.message})
            return {"answer": refusal.message, "citations": [], "edit_proposal": None}

    emit(run_id, "edit_delegation_finished", {"status": draft["status"], "timed_out": timed_out})
    return {"answer": _answer(name, draft, timed_out), "citations": [], "edit_proposal": proposal}
