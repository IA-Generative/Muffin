import re
from typing import Any

from app.backend_client import backend_client
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.llm import json_chat
from app.graph.state import AgentState

# Verbs (French and English) of a request to change a document. A cheap gate: most questions never
# contain one, and then neither the backend nor the model is bothered - the user's documents are
# only listed, and a model asked, for a message that looks like an edit.
_EDIT_VERBS = re.compile(
    r"\b(ajout\w*|rajout\w*|modifi\w*|supprim\w*|retir\w*|enlèv\w*|enlev\w*|remplac\w*|corrig\w*|chang\w*|"
    r"mets? à jour|mettre à jour|mise à jour|insèr\w*|insér\w*|réécri\w*|reecri\w*|reformul\w*|complèt\w*|"
    r"renomm\w*|raccourc\w*|allong\w*|add|edit|update|remove|delete|replace|change|fix|insert|rewrite|"
    r"append|rephrase|shorten)\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "The user may be asking to CHANGE one of their living documents (a document they can edit, listed "
    "below) rather than asking a question about their content. Decide, and reply only with a JSON "
    'object with keys: "edit" (bool - true only if the message asks to modify, add to, remove from or '
    'rewrite a document; false for a question, a search, or anything else), "document_id" (string - the '
    'id of the one listed document the user means, or null), "candidates" (array of ids - only when '
    '"edit" is true and the message could mean several of the listed documents and nothing in it or '
    'in the conversation tells which), "instruction" (string - the change to make, restated so it '
    "stands on its own, in the user's own words and terms: do not translate or reformulate names, "
    "titles or figures).\n\n"
    'Which document: only set "document_id" when the message names the document or clearly points to '
    'it (by its title, its subject, or the conversation so far). A generic reference such as "the '
    'document", "the file", "le document" or "it" with nothing else to tell which one is NOT enough: '
    'set "document_id" to null and list every document that could be meant in "candidates" - guessing '
    "would change the wrong document.\n\n"
    'Be conservative: when in doubt, "edit" is false - answering a question is harmless, changing a '
    "document is not. A message about a document that is NOT in the list is not an edit of a listed "
    "document: answer false."
)

_FALLBACK: dict[str, Any] = {"edit": False}


def _catalogue(documents: list[dict[str, Any]]) -> str:
    lines = []
    for document in documents:
        summary = f" - {document['summary']}" if document.get("summary") else ""
        where = f"collection « {document['collection_name']} »"
        lines.append(f"- id={document['document_id']} | « {document['name']} » ({where}){summary}")
    return "\n".join(lines)


def _clarification(documents: list[dict[str, Any]], candidate_ids: list[str]) -> str:
    named = [d for d in documents if d["document_id"] in candidate_ids] or documents
    options = "\n".join(f"- « {d['name']} » (collection « {d['collection_name']} »)" for d in named)
    return (
        "Plusieurs documents modifiables pourraient correspondre à votre demande. "
        f"Lequel voulez-vous modifier ?\n{options}"
    )


def detect_edit(state: AgentState) -> dict[str, Any]:
    """Recognises a request to change a living document (#171) before the research pipeline would
    treat it as a question and search for nothing. Sets `edit_target` when it is one - the
    delegate_edit node then hands it to the editing agent; otherwise the run goes on as usual.

    The list of what the user may edit comes from the backend, computed from the run's own identity
    snapshot: the model only ever picks among documents the user is allowed to change."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}
    query = state["original_query"]
    model = state["chat_model"]
    if model is None or not _EDIT_VERBS.search(query):
        return {"edit_target": None}

    documents = backend_client.list_editable_documents(run_id)
    if not documents:
        return {"edit_target": None}

    set_activity(run_id, "detect_edit", "Checking whether you want to change a document")
    history = state["messages"][:-1]
    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    user_content = f"Documents the user can edit:\n{_catalogue(documents)}\n\n"
    if history_text:
        user_content += f"Conversation so far:\n{history_text}\n\n"
    user_content += f"Current message: {query}"
    verdict = json_chat(model, _SYSTEM_PROMPT, user_content, fallback=_FALLBACK)
    if not isinstance(verdict, dict) or not verdict.get("edit"):
        return {"edit_target": None}

    by_id = {d["document_id"]: d for d in documents}
    chosen = by_id.get(str(verdict.get("document_id") or ""))
    instruction = str(verdict.get("instruction") or "").strip() or query
    if chosen is None:
        candidates = [str(c) for c in (verdict.get("candidates") or []) if str(c) in by_id]
        if len(candidates) < 2:
            # Said "edit" but named nothing it was offered: treat it as an ordinary question rather
            # than guess - and never act on an id the user wasn't offered.
            return {"edit_target": None}
        emit(run_id, "edit_target_ambiguous", {"candidates": candidates})
        return {"edit_target": {"clarification": _clarification(documents, candidates)}}

    emit(run_id, "edit_target_detected", {"document_id": chosen["document_id"], "document": chosen["name"]})
    return {
        "edit_target": {
            "document_id": chosen["document_id"],
            "document_name": chosen["name"],
            "collection_id": chosen["collection_id"],
            "instruction": instruction,
        }
    }
