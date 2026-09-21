from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.graph.services.llm import json_chat

_SYSTEM_PROMPT = (
    "Given a research task's query and a catalogue of knowledge bases (id, name, description), select the "
    "ones relevant to answering it. Respond only with a JSON array of the relevant ids (a subset of the "
    "given ids, or all of them if several are relevant)."
)

# Below this many accessible collections, the full catalogue is small enough to just send to the
# LLM as-is (today's behaviour) - the vector pre-filter below exists to bound the catalogue size
# for a user with many more than this, not to improve quality on an already-small set.
_VECTOR_PREFILTER_THRESHOLD = 20
# How many candidates the vector pre-filter keeps for the LLM to arbitrate over - large enough
# that a genuinely relevant collection ranked a bit low by embedding similarity alone still gets
# a chance in front of the LLM, small enough to actually bound the catalogue.
_VECTOR_PREFILTER_TOP_K = 20


def _vector_prefilter(query: str, accessible_vdbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Narrows a large accessible set down to `_VECTOR_PREFILTER_TOP_K` candidates by comparing
    the query's embedding to each collection's description embedding (§124) - never the security
    boundary itself (that's `accessible_vdbs`, already filtered by the backend), just a relevance
    pre-filter so the LLM catalogue below doesn't grow unbounded with the user's total accessible
    collection count. Falls back to the full set on any failure (no embedding model configured,
    Meilisearch unreachable, etc.) - same fail-open philosophy as the LLM call below."""
    try:
        scored = backend_client.search_collections(
            [str(v["id"]) for v in accessible_vdbs], query, _VECTOR_PREFILTER_TOP_K
        )
    except Exception:
        logger.exception("Collection-description vector pre-filter failed, falling back to every accessible VDB")
        return accessible_vdbs
    if not scored:
        return accessible_vdbs
    kept_ids = {str(item["collection_id"]) for item in scored}
    return [v for v in accessible_vdbs if str(v["id"]) in kept_ids]


def select_relevant_vdbs(
    query: str, accessible_vdbs: list[dict[str, Any]], model: str | None, pinned_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """VDB relevance (§12) - neither the vector pre-filter nor the LLM can ever widen
    `accessible_vdbs`, only narrow it. The intersection with it is the actual security boundary;
    everything below is just relevance ranking on top of a set the backend already restricted to
    what this user can reach.

    `pinned_ids` are collections the user explicitly attached to this message (the chat
    composer's "+" picker) - always included in the result (still intersected with
    accessible_vdbs), even if neither the pre-filter nor the LLM itself would have picked them:
    the user asked for them by name, that overrides a relevance guess."""
    if not accessible_vdbs:
        return []

    pinned = [v for v in accessible_vdbs if str(v["id"]) in set(pinned_ids or [])]

    if model is None or len(accessible_vdbs) == 1:
        return accessible_vdbs

    candidates = accessible_vdbs
    if len(accessible_vdbs) > _VECTOR_PREFILTER_THRESHOLD:
        candidates = _vector_prefilter(query, accessible_vdbs)
        # A pinned collection the pre-filter dropped must still reach the LLM catalogue - it's
        # the user's explicit choice, not a relevance guess the pre-filter gets to override.
        missing_pinned = [v for v in pinned if v not in candidates]
        candidates = candidates + missing_pinned

    catalogue = [{"id": str(v["id"]), "name": v["name"], "description": v["description"]} for v in candidates]
    try:
        selected_ids = json_chat(
            model, _SYSTEM_PROMPT, f"Query: {query}\n\nKnowledge bases: {catalogue}", fallback=None
        )
        if selected_ids is None:
            return candidates
        selected_ids = {str(item) for item in selected_ids}
    except Exception:
        logger.exception("VDB routing failed, falling back to every candidate VDB")
        return candidates

    selected = [v for v in candidates if str(v["id"]) in selected_ids] or candidates
    missing_pinned = [v for v in pinned if v not in selected]
    return selected + missing_pinned
