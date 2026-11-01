"""Which collections the plan is shown, and how a collection is named: no model is asked to route here."""

from typing import Any

from loguru import logger

from app.agent.backend_client import backend_client
from app.core.habits import MAX_ROUTING_BONUS

# Below this many accessible collections, the whole catalogue is small enough to give to the plan as it is; the vector
# pre-filter exists to bound it for a user with many more.
VECTOR_PREFILTER_THRESHOLD = 20
# How many collections the pre-filter keeps: enough that a relevant one ranked a little low by embedding similarity
# alone still reaches the plan, few enough to bound the catalogue.
_VECTOR_PREFILTER_TOP_K = 20

_PATH_SEPARATOR = " › "


async def vector_prefilter(
    query: str, accessible_vdbs: list[dict[str, Any]], habits: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    """Narrows a large accessible set down to `_VECTOR_PREFILTER_TOP_K` candidates by comparing
    the query's embedding to each collection's description embedding (§124) - never the security
    boundary itself (that's `accessible_vdbs`, already filtered by the backend), just a relevance
    pre-filter so the LLM catalogue below doesn't grow unbounded with the user's total accessible
    collection count. Falls back to the full set on any failure (no embedding model configured,
    Qdrant unreachable, etc.) - same fail-open philosophy as the LLM call below.

    The collections the person is used to (#286) count a few per cent more (`habits`: id -> weight, 0 to 1): a prior
    that turns only a comparable relevance - never one that leaves out a collection that fits clearly better, and never
    one the person cannot read, since only `accessible_vdbs` is ever searched."""
    habits = habits or {}
    try:
        scored = await backend_client.search_collections(
            [str(v["id"]) for v in accessible_vdbs], query, _VECTOR_PREFILTER_TOP_K + min(len(habits), 5)
        )
    except Exception:
        logger.exception("Collection-description vector pre-filter failed, falling back to every accessible VDB")
        return accessible_vdbs
    if not scored:
        return accessible_vdbs
    if habits:
        scored = sorted(
            scored,
            key=lambda item: (
                float(item.get("score") or 0.0) * (1 + MAX_ROUTING_BONUS * habits.get(str(item["collection_id"]), 0.0))
            ),
            reverse=True,
        )
    kept_ids = {str(item["collection_id"]) for item in scored[:_VECTOR_PREFILTER_TOP_K]}
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
