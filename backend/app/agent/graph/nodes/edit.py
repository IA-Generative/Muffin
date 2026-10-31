"""The sub-graph of a change to a living document (#171): validate the document the plan chose, ask the editing agent,
wait for its verdict, report it. This agent never edits anything itself: it asks the backend to start the edit - which
creates the draft, takes the document's lock and sends the job to the editing agent - then follows the draft until that
agent is done. Whether the user may edit the document is the backend's call (from the run's own identity). Nothing is
written to the collection: the user validates the proposal from the chat card. No model is called here."""

import asyncio
import time
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from app.agent.backend_client import EditRequestRefused, backend_client
from app.agent.config import settings
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.node_metrics import measured


class EditState(TypedDict):
    run_id: str
    edit_target: dict[str, Any] | None
    edit_proposal: NotRequired[dict[str, Any] | None]
    answer: NotRequired[str | None]
    citations: NotRequired[list[dict[str, Any]]]
    cancelled: NotRequired[bool]
    # The draft the editing agent is working on, and whether the wait ran out.
    draft: NotRequired[dict[str, Any] | None]
    timed_out: NotRequired[bool]


# Module attribute (not closed over) so tests run the wait loop without really sleeping.
_sleep = asyncio.sleep


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


async def edit_resolve(state: EditState) -> dict[str, Any]:
    """What the plan chose, or what to tell the user when it could not choose (several documents fit)."""
    target = state["edit_target"] or {}
    if "clarification" in target:
        return {"answer": target["clarification"], "citations": [], "edit_proposal": None}
    if await is_cancelled(state["run_id"]):
        return {"cancelled": True}
    return {}


async def edit_request(state: EditState) -> dict[str, Any]:
    run_id, target = state["run_id"], state["edit_target"]
    name, document_id = target["document_name"], target["document_id"]
    await set_activity(run_id, "edit_request", f"Asking the editing agent to change « {name} »")
    await emit(run_id, "edit_delegated", {"document_id": document_id, "instruction": target["instruction"]})
    try:
        draft = await backend_client.create_edit_request(run_id, document_id, target["instruction"])
    except EditRequestRefused as refusal:
        await emit(run_id, "edit_refused", {"code": refusal.code, "message": refusal.message})
        # A proposal already waiting on this document is worth showing: that is where the user should go next.
        proposal = _proposal(target) if refusal.code == "draft_exists" else None
        return {"answer": refusal.message, "citations": [], "edit_proposal": proposal}
    return {"draft": draft}


async def edit_wait(state: EditState) -> dict[str, Any]:
    run_id, target = state["run_id"], state["edit_target"]
    draft = state["draft"]
    deadline = time.monotonic() + settings.EDIT_WAIT_SECONDS
    timed_out = False
    while draft["status"] == "pending":
        if time.monotonic() >= deadline:
            timed_out = True
            break
        await _sleep(settings.EDIT_POLL_SECONDS)
        if await is_cancelled(run_id):
            return {"cancelled": True}
        try:
            draft = await backend_client.get_edit_request(run_id, target["document_id"])
        except EditRequestRefused as refusal:
            # The draft is gone (refused from the UI, or it lapsed) while this run waited for it.
            await emit(run_id, "edit_refused", {"code": refusal.code, "message": refusal.message})
            return {"answer": refusal.message, "citations": [], "edit_proposal": None}
    return {"draft": draft, "timed_out": timed_out}


async def edit_report(state: EditState) -> dict[str, Any]:
    target, draft, timed_out = state["edit_target"], state["draft"], state.get("timed_out", False)
    await emit(state["run_id"], "edit_delegation_finished", {"status": draft["status"], "timed_out": timed_out})
    return {
        "answer": _answer(target["document_name"], draft, timed_out),
        "citations": [],
        "edit_proposal": _proposal(target),
    }


def _proposal(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "collection_id": target["collection_id"],
        "document_id": target["document_id"],
        "document_name": target["document_name"],
    }


def _done(state: EditState) -> str:
    """Out of the sub-graph as soon as something is answered (nothing to delegate, refused) or the run is cancelled."""
    return "end" if state.get("answer") is not None or state.get("cancelled") else "next"


def build_edit_graph():
    graph = StateGraph(EditState)
    for name, node in (
        ("edit_resolve", edit_resolve),
        ("edit_request", edit_request),
        ("edit_wait", edit_wait),
        ("edit_report", edit_report),
    ):
        graph.add_node(name, measured(name, node))
    graph.set_entry_point("edit_resolve")
    for source, target in (
        ("edit_resolve", "edit_request"),
        ("edit_request", "edit_wait"),
        ("edit_wait", "edit_report"),
    ):
        graph.add_conditional_edges(source, _done, {"next": target, "end": END})
    graph.add_edge("edit_report", END)
    return graph.compile()
