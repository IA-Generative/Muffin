from typing import Any

from loguru import logger

from app.graph.services.llm import json_chat

_SYSTEM_PROMPT = (
    "Given a research task's query and a catalogue of knowledge bases (id, name, description), select the "
    "ones relevant to answering it. Respond only with a JSON array of the relevant ids (a subset of the "
    "given ids, or all of them if several are relevant)."
)


def select_relevant_vdbs(
    query: str, accessible_vdbs: list[dict[str, Any]], model: str | None, pinned_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """VDB relevance (§12) - the LLM only ever narrows `accessible_vdbs`, it can never widen it.
    The intersection below is the actual security boundary; the LLM call is just relevance
    ranking on top of a set the backend already restricted to what this user can reach.

    `pinned_ids` are collections the user explicitly attached to this message (the chat
    composer's "+" picker) - always included in the result (still intersected with
    accessible_vdbs), even if the LLM itself wouldn't have picked them: the user asked for them
    by name, that overrides a relevance guess."""
    if not accessible_vdbs:
        return []

    pinned = [v for v in accessible_vdbs if str(v["id"]) in set(pinned_ids or [])]

    if model is None or len(accessible_vdbs) == 1:
        return accessible_vdbs

    catalogue = [{"id": str(v["id"]), "name": v["name"], "description": v["description"]} for v in accessible_vdbs]
    try:
        selected_ids = json_chat(
            model, _SYSTEM_PROMPT, f"Query: {query}\n\nKnowledge bases: {catalogue}", fallback=None
        )
        if selected_ids is None:
            return accessible_vdbs
        selected_ids = {str(item) for item in selected_ids}
    except Exception:
        logger.exception("VDB routing failed, falling back to every accessible VDB")
        return accessible_vdbs

    selected = [v for v in accessible_vdbs if str(v["id"]) in selected_ids] or accessible_vdbs
    missing_pinned = [v for v in pinned if v not in selected]
    return selected + missing_pinned
