from collections import defaultdict
from typing import Any, NamedTuple

from loguru import logger

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.llm import json_chat

_SYSTEM_PROMPT = (
    "Given a research task's query and a catalogue of knowledge bases (id, name, description, and for one "
    "nested in another, its path), select the ones relevant to answering it. Respond only with a JSON array "
    "of the relevant ids (a subset of the given ids, or all of them if several are relevant)."
)

# Below this many accessible collections, the full catalogue is small enough to just send to the
# LLM as-is (today's behaviour) - the vector pre-filter below exists to bound the catalogue size
# for a user with many more than this, not to improve quality on an already-small set.
_VECTOR_PREFILTER_THRESHOLD = 20
# How many candidates the vector pre-filter keeps for the LLM to arbitrate over - large enough
# that a genuinely relevant collection ranked a bit low by embedding similarity alone still gets
# a chance in front of the LLM, small enough to actually bound the catalogue.
_VECTOR_PREFILTER_TOP_K = 20

_PATH_SEPARATOR = " › "


class RoutingScope(NamedTuple):
    """What, beyond the query, steers routing for one run: the collections the user attached to
    the message, and those a "go further" follow-up resumes from (#219, #233)."""

    pinned_ids: list[str]
    resume_from_ids: list[str]


class RoutingResult(NamedTuple):
    # The collections to search, in selection order.
    selected: list[dict[str, Any]]
    # Selected collections with sub-collections routing never looked at (#233) - where a "go
    # further" follow-up resumes from. Always empty for a set without sub-collections.
    unexplored: list[dict[str, Any]]


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
    query: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    pinned_ids: list[str] | None = None,
    resume_from_ids: list[str] | None = None,
) -> RoutingResult:
    """VDB relevance (§12) - neither the vector pre-filter nor the LLM can ever widen
    `accessible_vdbs`, only narrow it. The intersection with it is the actual security boundary;
    everything below is just relevance ranking on top of a set the backend already restricted to
    what this user can reach.

    `pinned_ids` are collections the user explicitly attached to this message (the chat
    composer's "+" picker) - always included in the result (still intersected with
    accessible_vdbs), even if neither the pre-filter nor the LLM itself would have picked them:
    the user asked for them by name, that overrides a relevance guess.

    Sub-collections are routed flat (#233): every accessible collection, at any level, competes on
    its own description (a parent's is rolled up from its sub-collections, #218), so a deep,
    specific one is found in the same single LLM call as a top-level one. With sub-collections,
    at most MAX_ROUTED_COLLECTIONS are kept, and the selected collections with sub-collections the
    LLM never saw (cut by the pre-filter or by that cap) are reported as unexplored.
    `resume_from_ids` (a "go further" follow-up) routes over the sub-collections of those only.
    A set without sub-collections is routed exactly as before.
    """
    if not accessible_vdbs:
        return RoutingResult([], [])

    pinned = [v for v in accessible_vdbs if str(v["id"]) in set(pinned_ids or [])]
    by_id = {str(v["id"]): v for v in accessible_vdbs}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vdb in accessible_vdbs:
        parent_id = str(vdb.get("parent_id") or "")
        if parent_id in by_id:
            children[parent_id].append(vdb)

    if not children:
        selected, _shown = _route(query, accessible_vdbs, model, pinned, by_id, fall_back_to_all=True)
        return RoutingResult(selected, [])

    resume_from = [by_id[vdb_id] for vdb_id in resume_from_ids or [] if vdb_id in by_id]
    if resume_from:
        # Already searched by the previous answer - only what's below them is new. Picking none
        # of it searches them again rather than nothing (or everything).
        pool = _unique([d for vdb in resume_from for d in _descendants(vdb, children)])
        picked, shown = _route(query, pool, model, [], by_id, fall_back_to_all=False) if pool else ([], set())
        picked = picked or resume_from
    else:
        picked, shown = _route(query, accessible_vdbs, model, pinned, by_id, fall_back_to_all=True)

    selected = picked[: settings.MAX_ROUTED_COLLECTIONS]
    selected_ids = {str(v["id"]) for v in selected}
    # Never seen by the LLM: under a selected collection, cut by the pre-filter...
    unexplored = [vdb for vdb in selected if any(str(d["id"]) not in shown for d in _descendants(vdb, children))]
    # ...or picked but over the cap: the nearest selected ancestor is where to resume from.
    for vdb in picked[settings.MAX_ROUTED_COLLECTIONS :]:
        ancestor = _nearest_ancestor_in(vdb, selected_ids, by_id)
        if ancestor is not None:
            unexplored.append(ancestor)

    selected += [vdb for vdb in pinned if vdb not in selected]
    return RoutingResult(selected, _unique(unexplored))


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


def _route(
    query: str,
    candidates_pool: list[dict[str, Any]],
    model: str | None,
    pinned: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    *,
    fall_back_to_all: bool,
) -> tuple[list[dict[str, Any]], set[str]]:
    """One routing pass over a flat pool: the selected collections, and the ids the LLM was shown.
    `fall_back_to_all` keeps every candidate rather than none when the LLM picks nothing or fails
    - missing the right collection costs more than searching a few extra - except when resuming,
    where the caller has a better fallback."""
    if model is None or len(candidates_pool) == 1:
        return candidates_pool, {str(v["id"]) for v in candidates_pool}

    candidates = candidates_pool
    if len(candidates_pool) > _VECTOR_PREFILTER_THRESHOLD:
        candidates = _vector_prefilter(query, candidates_pool)
        # A pinned collection the pre-filter dropped must still reach the LLM catalogue - it's
        # the user's explicit choice, not a relevance guess the pre-filter gets to override.
        missing_pinned = [v for v in pinned if v not in candidates]
        candidates = candidates + missing_pinned
    shown = {str(v["id"]) for v in candidates}
    fallback = candidates if fall_back_to_all else []

    catalogue = [_catalogue_entry(v, by_id) for v in candidates]
    try:
        selected_ids = json_chat(
            model, _SYSTEM_PROMPT, f"Query: {query}\n\nKnowledge bases: {catalogue}", fallback=None
        )
        if not isinstance(selected_ids, list):
            return fallback, shown
        selected_ids = {str(item) for item in selected_ids}
    except Exception:
        logger.exception("VDB routing failed, falling back to every candidate VDB")
        return fallback, shown

    selected = [v for v in candidates if str(v["id"]) in selected_ids] or fallback
    missing_pinned = [v for v in pinned if v not in selected]
    return selected + missing_pinned, shown


def _catalogue_entry(vdb: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """A nested collection is shown with its path, so a short description like "2024 reports"
    still reads in context - a top-level one (or any collection of a flat set) exactly as before."""
    entry = {"id": str(vdb["id"]), "name": vdb["name"], "description": vdb["description"]}
    if str(vdb.get("parent_id") or "") in by_id:
        entry["path"] = collection_path(vdb, by_id)
    return entry


def _descendants(vdb: dict[str, Any], children: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every accessible collection below this one, never itself - guarded against cycles."""
    found: list[dict[str, Any]] = []
    seen = {str(vdb["id"])}
    stack = list(children.get(str(vdb["id"]), []))
    while stack:
        child = stack.pop()
        if str(child["id"]) in seen:
            continue
        seen.add(str(child["id"]))
        found.append(child)
        stack.extend(children.get(str(child["id"]), []))
    return found


def _nearest_ancestor_in(vdb: dict[str, Any], ids: set[str], by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    seen = {str(vdb["id"])}
    parent_id = str(vdb.get("parent_id") or "")
    while parent_id in by_id and parent_id not in seen:
        if parent_id in ids:
            return by_id[parent_id]
        seen.add(parent_id)
        parent_id = str(by_id[parent_id].get("parent_id") or "")
    return None


def _unique(vdbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({str(v["id"]): v for v in vdbs}.values())
