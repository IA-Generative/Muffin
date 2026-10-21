import re
from typing import Any

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat, strip_code_fence
from app.graph.state import AgentState

# Verbs (French and English) of a request to write a new document. A cheap gate, like detect_edit's:
# most questions never contain one, and then neither the backend nor the model is bothered.
_CREATE_VERBS = re.compile(
    r"\b(cr[ée]{1,2}r?|cr[ée]{1,2}z|cr[ée]{1,2}s|r[ée]dig\w*|[ée]cri(?:s|re|vez)|g[ée]n[èé]r(?:e|er|ez)|"
    r"nouveau (?:document|fichier)|nouvelle (?:note|page|fiche)|"
    r"create|write|draft|generate|compose|new (?:document|file|note|page))\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "The user may be asking you to CREATE a new document - a file to keep in one of their collections - "
    "rather than asking a question. The collections they may add a document to are listed below. Decide, "
    'and reply only with a JSON object with keys: "create" (bool - true only if the message asks to write, '
    "draft or create a new document, note, page or file to be kept; false for a question, a search, a "
    "change to an EXISTING document, or a request for an answer in the chat), "
    '"markdown" (bool - false only when the user explicitly asks for a format other than Markdown, such as '
    "Word, docx, odt, pdf, Excel, csv or PowerPoint; true otherwise, including when no format is named), "
    '"collection_id" (string - the id of the one listed collection the document goes in, or null), '
    '"candidates" (array of ids - only when "create" is true and the message could mean several of the '
    'listed collections and nothing in it or in the conversation tells which), "title" (string - a short '
    'title for the document, in the user\'s language), "instruction" (string - what the document must '
    "contain, restated so it stands on its own, in the user's own words and terms: do not translate or "
    "reformulate names, titles or figures).\n\n"
    'Which collection: only set "collection_id" when the message names the collection or clearly points '
    "to it (by its name, its subject, or the conversation so far). Otherwise set it to null and list "
    'every collection that could be meant in "candidates" - guessing would put the document in the wrong '
    "place.\n\n"
    'Be conservative: when in doubt, "create" is false - answering a question is harmless, creating a '
    "document is not."
)

_WRITER_PROMPT = (
    "You write a document for the user, in Markdown. Reply with the Markdown document only: no preamble, "
    "no explanation, and no code fence around it. Start with a level-1 heading that is the document's "
    "title, then structure it with headings, lists and tables only where they help. Write in the language "
    "of the request. Use only what the request and the conversation tell you: never invent facts, "
    "figures, names, phone numbers, dates or references. Where information is missing, keep the section "
    "general or leave a short placeholder in square brackets for the user to fill in."
)

_FALLBACK: dict[str, Any] = {"create": False}
_NOT_MARKDOWN = (
    "Je ne peux créer que des documents au format Markdown (.md). Voulez-vous que je rédige celui-ci en Markdown ?"
)
_NO_COLLECTION = "Vous n'avez aucune collection dans laquelle je puisse créer un document."
_TITLE = re.compile(r"^\s*#\s+(.+?)\s*#*\s*$", re.MULTILINE)
_NAME_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_NAME_CHARS = 100


def _catalogue(collections: list[dict[str, Any]]) -> str:
    lines = []
    for collection in collections:
        description = f" - {collection['description']}" if collection.get("description") else ""
        lines.append(f"- id={collection['collection_id']} | « {collection['name']} »{description}")
    return "\n".join(lines) or "(none)"


def _clarification(collections: list[dict[str, Any]], candidate_ids: list[str]) -> str:
    named = [c for c in collections if c["collection_id"] in candidate_ids] or collections
    options = "\n".join(f"- « {c['name']} »" for c in named)
    return f"Dans quelle collection voulez-vous créer ce document ?\n{options}"


def detect_create(state: AgentState) -> dict[str, Any]:
    """Recognises a request to write a new document - Markdown only - before the research pipeline
    would treat it as a question. Sets `create_target` when it is one: the delegate_create node then
    writes the document and proposes it; otherwise the run goes on as usual.

    The collections it may be created in come from the backend, computed from the run's own identity
    snapshot: the model only ever picks among collections the user may add documents to."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}
    query = state["original_query"]
    model = state["chat_model"]
    if model is None or not _CREATE_VERBS.search(query):
        return {"create_target": None}

    collections = backend_client.list_editable_collections(run_id)

    set_activity(run_id, "detect_create", "Checking whether you want to create a document")
    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in state["messages"][:-1])
    user_content = f"Collections the user can add a document to:\n{_catalogue(collections)}\n\n"
    if history_text:
        user_content += f"Conversation so far:\n{history_text}\n\n"
    user_content += f"Current message: {query}"
    verdict = json_chat(model, _SYSTEM_PROMPT, user_content, fallback=_FALLBACK)
    if not isinstance(verdict, dict) or not verdict.get("create"):
        return {"create_target": None}

    if verdict.get("markdown") is False:
        emit(run_id, "create_refused", {"reason": "not_markdown"})
        return {"create_target": {"clarification": _NOT_MARKDOWN}}
    if not collections:
        emit(run_id, "create_refused", {"reason": "no_collection"})
        return {"create_target": {"clarification": _NO_COLLECTION}}

    by_id = {c["collection_id"]: c for c in collections}
    chosen = by_id.get(str(verdict.get("collection_id") or ""))
    if chosen is None and len(collections) == 1:
        chosen = collections[0]
    if chosen is None:
        candidates = [str(c) for c in (verdict.get("candidates") or []) if str(c) in by_id]
        emit(run_id, "create_target_ambiguous", {"candidates": candidates})
        return {"create_target": {"clarification": _clarification(collections, candidates)}}

    emit(run_id, "create_target_detected", {"collection_id": chosen["collection_id"], "collection": chosen["name"]})
    return {
        "create_target": {
            "collection_id": chosen["collection_id"],
            "collection_name": chosen["name"],
            "title": str(verdict.get("title") or "").strip(),
            "instruction": str(verdict.get("instruction") or "").strip() or query,
        }
    }


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


def delegate_create(state: AgentState) -> dict[str, Any]:
    """Writes the document the user asked for and proposes it - it is not created here.

    The text is written from the request and the conversation, without searching the collections.
    What comes back is a proposal stored with the run (`edit_proposal`, kind "create"): the chat shows
    it as a card with the Markdown, and the document only exists once the user validates it - the
    backend then creates it with the user's own rights, so this node never writes to a collection."""
    run_id = state["run_id"]
    target = state["create_target"] or {}

    # Nothing to write yet: the user has to say where, or in which format.
    if "clarification" in target:
        return {"answer": target["clarification"], "citations": [], "edit_proposal": None}
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "delegate_create", f"Writing a document for « {target['collection_name']} »")
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
