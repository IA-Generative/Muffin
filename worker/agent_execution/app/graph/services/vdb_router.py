from collections import defaultdict
from typing import Any, NamedTuple

from loguru import logger

from app.backend_client import backend_client
from app.config import settings
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

_DESCENT_PROMPT = (
    "Given a research task's query and a catalogue of sub-collections (id, path, description) of knowledge "
    "bases already found relevant, select the sub-collections worth searching for this query. Respond only "
    "with a JSON array of their ids - an empty array if none of them is relevant."
)

_PATH_SEPARATOR = " › "


class RoutingScope(NamedTuple):
    """What, beyond the query, steers routing for one run: the collections the user attached to
    the message, and those a "go further" follow-up resumes the descent from (#219)."""

    pinned_ids: list[str]
    resume_from_ids: list[str]


class RoutingResult(NamedTuple):
    # The collections to search, in selection order.
    selected: list[dict[str, Any]]
    # Selected collections whose sub-collections the descent didn't get to within its budget
    # (#219) - where a "go further" follow-up resumes from. Always empty for a flat set.
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

    With sub-collections (#219), routing descends the tree instead of picking from every level at
    once: the top-level collections first, then the sub-collections of those it kept, one level
    at a time, within MAX_COLLECTION_DESCENT_DEPTH and MAX_ROUTED_COLLECTIONS. `resume_from_ids`
    (a "go further" follow-up) starts that descent below the collections the previous answer left
    unexplored instead. A set with no sub-collection at all is routed exactly as before.
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

    if not children or model is None:
        return RoutingResult(_select_flat(query, accessible_vdbs, model, pinned), [])

    resume_from = [by_id[vdb_id] for vdb_id in resume_from_ids or [] if vdb_id in by_id]
    if resume_from:
        # Already searched by the previous answer - only what's below them is new.
        selected: list[dict[str, Any]] = []
        level = resume_from
    else:
        # A collection whose parent isn't readable by this user counts as top-level for them.
        roots = [vdb for vdb in accessible_vdbs if str(vdb.get("parent_id") or "") not in by_id]
        selected = _select_flat(query, roots, model, [])[: settings.MAX_ROUTED_COLLECTIONS]
        level = selected

    unexplored: list[dict[str, Any]] = []
    for _depth in range(settings.MAX_COLLECTION_DESCENT_DEPTH):
        expandable = [vdb for vdb in level if children.get(str(vdb["id"]))]
        if not expandable:
            break
        room = settings.MAX_ROUTED_COLLECTIONS - len(selected)
        if room <= 0:
            unexplored += expandable
            break
        candidates = [child for vdb in expandable for child in children[str(vdb["id"])]]
        picked = _pick_sub_collections(query, candidates, by_id, model)
        if len(picked) > room:
            # Over budget: keep the first ones, and remember the parents of the rest.
            dropped_parent_ids = {str(vdb.get("parent_id")) for vdb in picked[room:]}
            unexplored += [vdb for vdb in expandable if str(vdb["id"]) in dropped_parent_ids]
            picked = picked[:room]
        selected += picked
        level = picked
    else:
        # Depth budget spent: whatever the last level kept may still have sub-collections.
        unexplored += [vdb for vdb in level if children.get(str(vdb["id"]))]

    if not selected:
        # A "go further" whose sub-collections turned out irrelevant: search where it resumed
        # from again rather than nothing (or everything).
        selected = list(resume_from)
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


def _select_flat(
    query: str, accessible_vdbs: list[dict[str, Any]], model: str | None, pinned: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Routing over a flat catalogue - the whole set before sub-collections existed, now also the
    top level of the tree. Falls back to every candidate rather than none when the LLM can't
    decide: missing the right collection costs more than searching a few extra."""
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


def _pick_sub_collections(
    query: str, candidates: list[dict[str, Any]], by_id: dict[str, dict[str, Any]], model: str
) -> list[dict[str, Any]]:
    """One LLM call for a whole level of the descent. Unlike the top level, picking none is a
    valid answer (the parents' own documents are searched anyway), and so is any failure: the
    descent just stops there."""
    catalogue = [
        {"id": str(v["id"]), "path": collection_path(v, by_id), "description": v["description"]} for v in candidates
    ]
    picked_ids = json_chat(model, _DESCENT_PROMPT, f"Query: {query}\n\nSub-collections: {catalogue}", fallback=[])
    if not isinstance(picked_ids, list):
        return []
    picked_ids = {str(item) for item in picked_ids}
    return [v for v in candidates if str(v["id"]) in picked_ids]


def _unique(vdbs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({str(v["id"]): v for v in vdbs}.values())
