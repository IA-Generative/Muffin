"""Which collections the plan is shown, and how a collection is named: no model is asked to route here."""

from typing import Any

from loguru import logger

from app.backend_client import backend_client

# Below this many accessible collections, the whole catalogue is small enough to give to the plan as it is; the vector
# pre-filter exists to bound it for a user with many more.
VECTOR_PREFILTER_THRESHOLD = 20
# How many collections the pre-filter keeps: enough that a relevant one ranked a little low by embedding similarity
# alone still reaches the plan, few enough to bound the catalogue.
_VECTOR_PREFILTER_TOP_K = 20

_PATH_SEPARATOR = " › "


def vector_prefilter(query: str, accessible_vdbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Narrows a large accessible set down to `_VECTOR_PREFILTER_TOP_K` candidates by comparing
    the query's embedding to each collection's description embedding (§124) - never the security
    boundary itself (that's `accessible_vdbs`, already filtered by the backend), just a relevance
    pre-filter so the LLM catalogue below doesn't grow unbounded with the user's total accessible
    collection count. Falls back to the full set on any failure (no embedding model configured,
    Qdrant unreachable, etc.) - same fail-open philosophy as the LLM call below."""
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


def collection_path_names(vdb: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    """["Root", "Child", vdb's name] through the collections in `by_id` (the user's accessible
    set) - an ancestor outside it is never named."""
    names = [vdb["name"]]
    seen = {str(vdb["id"])}
    parent_id = str(vdb.get("parent_id") or "")
    while parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id[parent_id]
        names.append(parent["name"])
        parent_id = str(parent.get("parent_id") or "")
    return list(reversed(names))


def collection_path(vdb: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    """ "Root › Child › vdb", see collection_path_names."""
    return _PATH_SEPARATOR.join(collection_path_names(vdb, by_id))


def catalogue_entry(vdb: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """A nested collection is shown with its path, so a short description like "2024 reports"
    still reads in context - a top-level one (or any collection of a flat set) exactly as before."""
    entry = {"id": str(vdb["id"]), "name": vdb["name"], "description": vdb["description"]}
    if str(vdb.get("parent_id") or "") in by_id:
        entry["path"] = collection_path(vdb, by_id)
    return entry
