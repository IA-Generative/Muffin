from typing import Any

from app.graph.services.llm import json_chat

_SYSTEM_PROMPT = (
    "Given a request for a specific document page and a list of candidate documents (id, name), identify "
    'which document and page number are being asked for. Respond only with a JSON object: {"document_id": '
    '"..." or null, "page_number": integer or null}. Use null for a field that cannot be determined.'
)


def resolve_document_page(
    query: str, candidates: list[dict[str, Any]], model: str | None
) -> tuple[str | None, int | None]:
    """Picks a document id + page number out of a fixed candidate list, never an id the LLM
    invents itself (§12 pattern applied to documents, not just VDBs) - the candidates are always
    the documents of a collection the backend already confirmed this user can reach."""
    if model is None or not candidates:
        return None, None

    catalogue = [{"id": str(c["id"]), "name": c["name"]} for c in candidates]
    raw = json_chat(model, _SYSTEM_PROMPT, f"Request: {query}\n\nCandidate documents: {catalogue}", fallback=None)
    if not isinstance(raw, dict):
        return None, None

    valid_ids = {str(c["id"]) for c in candidates}
    document_id = raw.get("document_id")
    document_id = str(document_id) if document_id is not None and str(document_id) in valid_ids else None
    page_number = raw.get("page_number")
    page_number = page_number if isinstance(page_number, int) else None
    return document_id, page_number
