"""The sub-graph of a new Markdown document (#169): validate the collection the plan chose, write the document. It is
not created here: what comes back is a proposal the chat shows as a card, and the document only exists once the user
validates it - the backend then creates it with the user's own rights."""

import re
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import strip_code_fence
from app.graph.services.node_metrics import measured


class CreateState(TypedDict):
    run_id: str
    chat_model: str | None
    messages: list[dict[str, Any]]
    create_target: dict[str, Any] | None
    edit_proposal: NotRequired[dict[str, Any] | None]
    answer: NotRequired[str | None]
    citations: NotRequired[list[dict[str, Any]]]
    cancelled: NotRequired[bool]


_WRITER_PROMPT = (
    "You write a document for the user, in Markdown. Reply with the Markdown document only: no preamble, "
    "no explanation, and no code fence around it. Start with a level-1 heading that is the document's "
    "title, then structure it with headings, lists and tables only where they help. Write in the language "
    "of the request. Use only what the request and the conversation tell you: never invent facts, "
    "figures, names, phone numbers, dates or references. Where information is missing, keep the section "
    "general or leave a short placeholder in square brackets for the user to fill in."
)

_TITLE = re.compile(r"^\s*#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_NAME_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_NAME_CHARS = 100


def _document_name(markdown: str, fallback: str) -> str:
    """The first heading, else the title the model gave; made safe to use as a file name."""
    found = _TITLE.search(markdown)
    name = _NAME_UNSAFE.sub(" ", (found.group(1) if found else fallback) or "Nouveau document")
    name = re.sub(r"\s+", " ", name).strip(" .") or "Nouveau document"
    return name[:_MAX_NAME_CHARS].rstrip()


def _bounded(markdown: str) -> str:
    """Cut at the last paragraph that fits: a document ending mid-sentence is worse than a shorter one."""
    if len(markdown) <= settings.CREATE_MAX_CHARS:
        return markdown
    cut = markdown[: settings.CREATE_MAX_CHARS]
    return cut[: cut.rfind("\n\n")].rstrip() if "\n\n" in cut else cut


def create_resolve(state: CreateState) -> dict[str, Any]:
    """What the plan chose, or what to tell the user when it could not (which collection? only Markdown is possible)."""
    target = state["create_target"] or {}
    if "clarification" in target:
        return {"answer": target["clarification"], "citations": [], "edit_proposal": None}
    if is_cancelled(state["run_id"]):
        return {"cancelled": True}
    return {}


def create_write(state: CreateState) -> dict[str, Any]:
    """Writes the document the user asked for and proposes it - it is not created here.

    The text is written from the request and the conversation, without searching the collections.
    What comes back is a proposal stored with the run (`edit_proposal`, kind "create"): the chat shows
    it as a card with the Markdown, and the document only exists once the user validates it - the
    backend then creates it with the user's own rights, so this node never writes to a collection."""
    run_id = state["run_id"]
    target = state["create_target"]

    set_activity(run_id, "create_write", f"Writing a document for « {target['collection_name']} »")
    emit(run_id, "create_delegated", {"collection_id": target["collection_id"]})
    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in state["messages"][:-1])
    user_content = f"Document to write: {target['instruction']}"
    if target.get("title"):
        user_content += f"\nSuggested title: {target['title']}"
    if history_text:
        user_content += f"\n\nConversation so far:\n{history_text}"
    markdown = ""
    try:
        raw = backend_client.llm_chat(
            state["chat_model"],
            [{"role": "system", "content": _WRITER_PROMPT}, {"role": "user", "content": user_content}],
            max_tokens=settings.CREATE_MAX_TOKENS,
        )
        markdown = _bounded(strip_code_fence(raw))
    except Exception:
        emit(run_id, "create_failed", {})
    if not markdown.strip():
        return {
            "answer": (
                "Je n'ai pas réussi à rédiger ce document. Pouvez-vous reformuler ou préciser ce qu'il doit contenir ?"
            ),
            "citations": [],
            "edit_proposal": None,
        }

    name = _document_name(markdown, target.get("title", ""))
    proposal = {
        "kind": "create",
        "status": "pending",
        "collection_id": target["collection_id"],
        "collection_name": target["collection_name"],
        "name": name,
        "content": markdown,
    }
    emit(run_id, "create_proposed", {"collection_id": target["collection_id"], "name": name})
    return {
        "answer": (
            f"J'ai rédigé le document « {name} » pour la collection « {target['collection_name']} ». "
            "Il n'est pas encore créé : relisez-le dans la carte ci-dessous, puis créez-le ou refusez-le."
        ),
        "citations": [],
        "edit_proposal": proposal,
    }


def _done(state: CreateState) -> str:
    return "end" if state.get("answer") is not None or state.get("cancelled") else "next"


def build_create_graph():
    graph = StateGraph(CreateState)
    graph.add_node("create_resolve", measured("create_resolve", create_resolve))
    graph.add_node("create_write", measured("create_write", create_write))
    graph.set_entry_point("create_resolve")
    graph.add_conditional_edges("create_resolve", _done, {"next": "create_write", "end": END})
    graph.add_edge("create_write", END)
    return graph.compile()
