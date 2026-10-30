import uuid
from collections.abc import Sequence

import numpy as np
from loguru import logger
from qdrant_client import models

from app.config import SearchSettings
from app.connectors import qdrant_connector
from app.core.bm25 import Bm25Encoder

# Three kinds of points live in one Qdrant collection per Muffin Collection (§ QA -> summaries -> chunks
# retrieval cascade): a chunk's embedding, a QA pair's question embedding and a document summary's embedding.
# They share the collection's embedding model, only this payload field says which kind a point is, so
# search()/search_qa()/search_summaries() below just filter on it.
_KIND_FIELD = "kind"
# Which document a point is from - the file it was cut out of, summarizes or is a question about (a collection's own
# QA pairs have none). Open WebUI writes the same in `metadata.file_id`.
_DOCUMENT_FIELD = "document_id"
_KIND_CHUNK = "chunk"
_KIND_QA = "qa"
_KIND_SUMMARY = "summary"
# The kinds of points, for what copies them from one document to another (#300).
KIND_CHUNK, KIND_QA, KIND_SUMMARY = _KIND_CHUNK, _KIND_QA, _KIND_SUMMARY

# Every point has two named vectors: the embedding, and the sparse BM25 vector of its text, whose IDF
# Qdrant computes from the statistics of the collection itself.
_DENSE = "dense"
_SPARSE = "sparse"

_settings = SearchSettings()
_encoder = Bm25Encoder(
    language=_settings.SEARCH_LANGUAGE,
    k1=_settings.SEARCH_BM25_K1,
    b=_settings.SEARCH_BM25_B,
    average_length=_settings.SEARCH_BM25_AVG_LENGTH,
)

_client = qdrant_connector.client

# Single global collection (unlike chunks_<collection_id>, one point per Muffin collection here - a
# description isn't chunked) holding every collection's description and tags, all always embedded with the
# same admin-configured model (see app/services/embedding_model_lookup.py) so a query can be compared
# against every collection's description in one embedding space. Used to narrow a large accessible set down
# to the most relevant candidates before an LLM call (§ VDB routing) and, later, to suggest a collection for
# an uploaded file (§122).
_COLLECTIONS = "collections"

_PAGE = 1000


# -- naming: one alias per Muffin collection, over one of its two physical collections ---------------
# Searches and writes go to the alias chunks_<id>, which never needs to know a rebuild (#12) is going on.
# That rebuild builds the other physical collection, then moves the alias onto it in one atomic operation:
# the two are used in turn, "next" being whichever the alias does not point to.


def _alias(collection_id: uuid.UUID) -> str:
    return f"chunks_{collection_id}"


def _physical(collection_id: uuid.UUID, slot: str) -> str:
    return f"chunks_{collection_id}_{slot}"


def _active_physical(collection_id: uuid.UUID) -> str | None:
    """The physical collection the alias points to, None when nothing was ever indexed."""
    alias = _alias(collection_id)
    for description in _client.get_aliases().aliases:
        if description.alias_name == alias:
            return description.collection_name
    return None


def _next_physical(collection_id: uuid.UUID) -> str:
    active = _active_physical(collection_id)
    return _physical(collection_id, "b" if active == _physical(collection_id, "a") else "a")


def _target(collection_id: uuid.UUID, next_index: bool) -> str:
    return _next_physical(collection_id) if next_index else _alias(collection_id)


def _exists(name: str) -> bool:
    return _client.collection_exists(name)


def _create_collection(name: str, dimensions: int) -> None:
    # Lazily created on first embedding - the dimension is whatever the collection's own embedding model
    # produces, never hardcoded.
    try:
        _client.create_collection(
            name,
            vectors_config={_DENSE: models.VectorParams(size=dimensions, distance=models.Distance.COSINE)},
            sparse_vectors_config={_SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    except Exception:
        if not _exists(name):  # a concurrent writer may have created it first
            raise
        return
    for field in (_KIND_FIELD, "collection_id", _DOCUMENT_FIELD):
        _client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)


def _ensure_active(collection_id: uuid.UUID, dimensions: int) -> str:
    """The alias, with a collection behind it - created now when nothing was indexed yet."""
    alias = _alias(collection_id)
    if _exists(alias):
        return alias
    # "a" may already be a rebuild being built while nothing is active yet: the active one is "b" then.
    physical = _physical(collection_id, "b" if _exists(_physical(collection_id, "a")) else "a")
    _create_collection(physical, dimensions)
    try:
        _client.update_collection_aliases(
            [models.CreateAliasOperation(create_alias=models.CreateAlias(collection_name=physical, alias_name=alias))]
        )
    except Exception:
        if not _exists(alias):
            raise
    return alias


def _ensure_next(collection_id: uuid.UUID, dimensions: int) -> str:
    name = _next_physical(collection_id)
    if not _exists(name):
        _create_collection(name, dimensions)
    return name


# -- writing ----------------------------------------------------------------------------------------


def _sparse(text: str) -> models.SparseVector:
    indices, values = _encoder.encode_document(text)
    return models.SparseVector(indices=indices, values=values)


def _point(
    collection_id: uuid.UUID,
    point_id: uuid.UUID,
    embedding: list[float],
    kind: str,
    text: str,
    model: str | None,
    document_id: uuid.UUID | None = None,
) -> models.PointStruct:
    payload = {_KIND_FIELD: kind, "collection_id": str(collection_id), "text": text}
    if document_id is not None:
        payload[_DOCUMENT_FIELD] = str(document_id)
    # Which model made the vector: what a rebuild (#12) checks to redo a vector made with another one.
    if model:
        payload["model"] = model
    return models.PointStruct(id=str(point_id), vector={_DENSE: embedding, _SPARSE: _sparse(text)}, payload=payload)


def _upsert(
    collection_id: uuid.UUID,
    point_id: uuid.UUID,
    embedding: list[float],
    kind: str,
    text: str = "",
    model: str | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    name = _ensure_active(collection_id, len(embedding))
    # wait: what is read right after (a document that reuses these results, #300) must already be there.
    _client.upsert(name, [_point(collection_id, point_id, embedding, kind, text, model, document_id)], wait=True)


def upsert_chunk_embedding(
    collection_id: uuid.UUID,
    chunk_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
    model: str | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    _upsert(collection_id, chunk_id, embedding, _KIND_CHUNK, text, model, document_id)


def upsert_qa_embedding(
    collection_id: uuid.UUID,
    qa_pair_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
    model: str | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    _upsert(collection_id, qa_pair_id, embedding, _KIND_QA, text, model, document_id)


def upsert_summary_embedding(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
    model: str | None = None,
) -> None:
    _upsert(collection_id, document_id, embedding, _KIND_SUMMARY, text, model, document_id)


# -- hybrid search ----------------------------------------------------------------------------------


def _branches(query: str, query_embedding: list[float], flt: models.Filter) -> list[tuple[str, models.Prefetch]]:
    """The two searches the fusion merges: by embedding, and by BM25 terms (none when the query has no term
    left once stop words are gone - the dense branch alone then answers)."""
    limit = _settings.SEARCH_PREFETCH_LIMIT
    branches = [(_DENSE, models.Prefetch(query=query_embedding, using=_DENSE, filter=flt, limit=limit))]
    indices, values = _encoder.encode_query(query)
    if indices:
        sparse = models.SparseVector(indices=indices, values=values)
        branches.append((_SPARSE, models.Prefetch(query=sparse, using=_SPARSE, filter=flt, limit=limit)))
    return branches


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / norm) if norm else 0.0


def _hybrid(
    name: str, query: str, query_embedding: list[float], limit: int, flt: models.Filter
) -> list[tuple[uuid.UUID, float]]:
    """Hits ordered by the Reciprocal Rank Fusion of the dense and the BM25 branches, each with the cosine
    between the query and the point's own embedding as its score.

    A fused score only says how the ranks of a point in the two branches add up - it changes with the
    number of candidates, and says nothing of how close the point is. The cosine does, the same way
    for every query and whichever branch found the point (a point only the lexical branch found still
    has one), which is what the research agent compares to a threshold to tell that a question was
    already answered."""
    if not _exists(name):
        return []
    branches = _branches(query, query_embedding, flt)
    weights = {_DENSE: _settings.SEARCH_DENSE_WEIGHT, _SPARSE: _settings.SEARCH_SPARSE_WEIGHT}
    fusion = models.Rrf(k=_settings.SEARCH_RRF_K, weights=[weights[branch] for branch, _ in branches])
    result = _client.query_points(
        name,
        prefetch=[prefetch for _, prefetch in branches],
        query=models.RrfQuery(rrf=fusion),
        limit=limit,
        with_vectors=[_DENSE],
    )
    hits = [
        (uuid.UUID(str(point.id)), _cosine(query_embedding, point.vector[_DENSE]))
        for point in result.points
        if isinstance(point.vector, dict) and _DENSE in point.vector
    ]
    if _settings.SEARCH_LOG_BRANCHES:
        _log_branches(name, hits, branches, limit)
    return hits


def _branch_ranks(
    name: str, branches: list[tuple[str, models.Prefetch]], limit: int
) -> dict[str, dict[uuid.UUID, int]]:
    """The rank (from 1) each branch alone gives to its candidates."""
    ranks: dict[str, dict[uuid.UUID, int]] = {}
    for branch, prefetch in branches:
        result = _client.query_points(
            name, query=prefetch.query, using=prefetch.using, query_filter=prefetch.filter, limit=limit
        )
        ranks[branch] = {uuid.UUID(str(point.id)): rank for rank, point in enumerate(result.points, start=1)}
    return ranks


def _log_branches(
    name: str, hits: list[tuple[uuid.UUID, float]], branches: list[tuple[str, models.Prefetch]], limit: int
) -> None:
    ranks = _branch_ranks(name, branches, _settings.SEARCH_PREFETCH_LIMIT)
    for position, (point_id, cosine) in enumerate(hits[:limit], start=1):
        by_branch = {branch: ranks[branch].get(point_id) for branch in ranks}
        logger.debug(f"search {name}: #{position} {point_id} cosine={cosine:.3f} branch ranks={by_branch}")


def _kind_filter(kind: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key=_KIND_FIELD, match=models.MatchValue(value=kind))])


def search(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _hybrid(_alias(collection_id), query, query_embedding, limit, _kind_filter(_KIND_CHUNK))


def search_any(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    """The collection's whole index, whatever a point is - a chunk, a QA pair or a summary - with no cascade (#467).
    The caller tells them apart by the id."""
    return _hybrid(_alias(collection_id), query, query_embedding, limit, models.Filter())


def search_qa(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _hybrid(_alias(collection_id), query, query_embedding, limit, _kind_filter(_KIND_QA))


def search_summaries(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _hybrid(_alias(collection_id), query, query_embedding, limit, _kind_filter(_KIND_SUMMARY))


def external_collection_name(external_id: str) -> str:
    """The Qdrant collection Open WebUI keeps a knowledge base's chunks in (#453)."""
    return f"{_settings.OWUI_QDRANT_PREFIX}_{external_id}"


def search_external(name: str, query_embedding: list[float], limit: int) -> list[tuple[uuid.UUID, float]]:
    """A collection another system keeps in this Qdrant (Open WebUI, #453), read where it is and left as it is.

    The same search as the dense branch of the others - the query's embedding against the points' - on the field
    that system writes: one vector, no name (`using` left out), no BM25 and no `kind`, so no fusion, no QA and no
    summaries. The score is the same too, the cosine, which a cosine collection returns as its score: a result
    competes with the other collections' on equal terms. The ids are those of the chunks copied into Postgres.

    What that system stored is not Muffin's to guarantee: if it re-embedded with another model, its vectors do not
    have the dimension of the query's and Qdrant refuses the search. That collection then contributes nothing and the
    search goes on with the others, as when a model fails to embed the query (the synchronisation reports the
    mismatch, #453)."""
    if not _exists(name):
        return []
    try:
        result = _client.query_points(name, query=query_embedding, limit=limit)
    except Exception:
        logger.exception(f"Failed to search the collection '{name}' of another system - it gives no result")
        return []
    return [(uuid.UUID(str(point.id)), point.score) for point in result.points]


def explain_search(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], kind: str = _KIND_CHUNK
) -> dict[str, dict[uuid.UUID, int]]:
    """What each branch of a search alone ranks - the contribution of the lexical and the dense side to a
    result, for debugging and tests (SEARCH_LOG_BRANCHES logs the same for every search)."""
    name = _alias(collection_id)
    if not _exists(name):
        return {}
    return _branch_ranks(name, _branches(query, query_embedding, _kind_filter(kind)), _settings.SEARCH_PREFETCH_LIMIT)


# -- deleting ---------------------------------------------------------------------------------------


def _delete_ids(names: Sequence[str], point_ids: Sequence[str]) -> None:
    selector = models.PointIdsList(points=list(point_ids))
    for name in names:
        if _exists(name):
            _client.delete(name, points_selector=selector, wait=True)


def _both_physicals(collection_id: uuid.UUID) -> tuple[str, str]:
    return _physical(collection_id, "a"), _physical(collection_id, "b")


def delete_document_embeddings(collection_id: uuid.UUID, document_id: uuid.UUID, chunk_ids: list[uuid.UUID]) -> None:
    """Best-effort cleanup of every Qdrant point tied to one document - the chunk embeddings (keyed by
    chunk_id) and the summary embedding (keyed by document_id itself, see upsert_summary_embedding). Called
    from delete_document/reprocess *before* the Postgres rows go away, so a Qdrant/network failure here only
    leaves orphaned vectors (never stale references the search path can still hit)."""
    ids = [str(document_id)] + [str(chunk_id) for chunk_id in chunk_ids]
    # Both collections: a rebuild's (#12) must not keep what the active one no longer has.
    for name in _both_physicals(collection_id):
        try:
            _delete_ids([name], ids)
        except Exception:
            logger.exception(f"Failed to delete document {document_id} embeddings from collection '{name}'")


def _delete_points(collection_id: uuid.UUID, ids: Sequence[uuid.UUID], what: str) -> None:
    """Best-effort removal of points from both of a collection's physical collections, same reasoning as
    delete_document_embeddings: a failure only leaves orphaned vectors, which the search paths never
    return since they resolve their ids against Postgres."""
    if not ids:
        return
    point_ids = [str(point_id) for point_id in ids]
    for name in _both_physicals(collection_id):
        try:
            _delete_ids([name], point_ids)
        except Exception:
            logger.exception(f"Failed to delete {len(point_ids)} {what} embedding(s) from collection '{name}'")


def delete_qa_embeddings(collection_id: uuid.UUID, qa_pair_ids: Sequence[uuid.UUID]) -> None:
    _delete_points(collection_id, qa_pair_ids, "QA pair")


def delete_chunk_embeddings(collection_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID]) -> None:
    _delete_points(collection_id, chunk_ids, "chunk")


def delete_qa_embedding(collection_id: uuid.UUID, qa_pair_id: uuid.UUID) -> None:
    delete_qa_embeddings(collection_id, [qa_pair_id])


def delete_collection(collection_id: uuid.UUID) -> None:
    """Best-effort, same reasoning as app/core/storage.py's delete_objects: called after the
    Collection row is already gone, so a Qdrant/network failure here must not roll that back - it just
    leaves an orphaned collection under an id nothing references anymore. Deleting a collection removes
    the alias that points to it.
    """
    for name in _both_physicals(collection_id):
        try:
            if _exists(name):
                _client.delete_collection(name)
        except Exception:
            logger.exception(f"Failed to delete Qdrant collection '{name}' - it is now orphaned")
    try:
        _delete_ids([_COLLECTIONS], [str(collection_id)])
    except Exception:
        logger.exception(f"Failed to remove collection {collection_id} from the '{_COLLECTIONS}' collection")


# -- reading ----------------------------------------------------------------------------------------


def read_vectors(
    collection_id: uuid.UUID, point_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[list[float], str | None]]:
    """The vectors of points of the collection's active index, with the model that made each - what a
    document that reuses another's results copies instead of embedding the same texts again (#300). A
    point that is not there (its embedding failed when it was made) is simply absent."""
    name = _alias(collection_id)
    if not point_ids or not _exists(name):
        return {}
    vectors: dict[uuid.UUID, tuple[list[float], str | None]] = {}
    for start in range(0, len(point_ids), _PAGE):
        records = _client.retrieve(
            name,
            [str(point_id) for point_id in point_ids[start : start + _PAGE]],
            with_payload=["model"],
            with_vectors=[_DENSE],
        )
        for record in records:
            if isinstance(record.vector, dict) and record.vector.get(_DENSE):
                vectors[uuid.UUID(str(record.id))] = (list(record.vector[_DENSE]), (record.payload or {}).get("model"))
    return vectors


# -- blue/green rebuild of a collection's index (#12) -----------------------------------------------
# The active index is reached through the alias chunks_<id>: searches never need to know a rebuild is going
# on. The new one is built in the other physical collection, then the alias is moved onto it in one atomic
# operation. The old collection stays, as "next", until the switch is validated (deleted) or rolled back
# (the alias moved back).


def list_points(collection_id: uuid.UUID, *, next_index: bool) -> dict[str, dict[str, str | None]]:
    """Every point of the index, by id: its kind, text and the model that made its vector (None for a
    point indexed before the model was recorded). What a rebuild compares to PostgreSQL."""
    name = _target(collection_id, next_index)
    if not _exists(name):
        return {}
    points: dict[str, dict[str, str | None]] = {}
    offset = None
    while True:
        records, offset = _client.scroll(
            name, limit=_PAGE, offset=offset, with_payload=[_KIND_FIELD, "text", "model"], with_vectors=False
        )
        for record in records:
            payload = record.payload or {}
            points[str(record.id)] = {
                "kind": payload.get(_KIND_FIELD),
                "text": payload.get("text"),
                "model": payload.get("model"),
            }
        if offset is None:
            return points


def upsert_points(
    collection_id: uuid.UUID,
    points: list[tuple[str, uuid.UUID, str, list[float]]],
    model: str,
    *,
    next_index: bool,
    documents: dict[uuid.UUID, uuid.UUID] | None = None,
) -> None:
    """(kind, id, text, embedding) points, all made with `model`, in one call. `documents`: the document of each
    point, by point id - a summary is its own document's, a point not in it has none."""
    if not points:
        return
    dimensions = len(points[0][3])
    name = _ensure_next(collection_id, dimensions) if next_index else _ensure_active(collection_id, dimensions)
    _client.upsert(
        name,
        [
            _point(
                collection_id,
                point_id,
                embedding,
                kind,
                text,
                model,
                point_id if kind == _KIND_SUMMARY else (documents or {}).get(point_id),
            )
            for kind, point_id, text, embedding in points
        ],
        wait=True,
    )


def delete_points(collection_id: uuid.UUID, point_ids: list[str], *, next_index: bool) -> None:
    if point_ids:
        _delete_ids([_target(collection_id, next_index)], point_ids)


def next_index_exists(collection_id: uuid.UUID) -> bool:
    return _exists(_next_physical(collection_id))


def delete_next_index(collection_id: uuid.UUID) -> None:
    name = _next_physical(collection_id)
    if _exists(name):
        _client.delete_collection(name)


def swap_with_next(collection_id: uuid.UUID) -> None:
    """Moves the alias from the active collection to the rebuilt one, atomically: every search before it
    reads the old one, every search after it the new one, never anything in between (a single request
    carries both operations). Raises if there is no rebuilt collection. A collection with nothing indexed
    before the rebuild simply gets its alias."""
    rebuilt = _next_physical(collection_id)
    if not _exists(rebuilt):
        raise RuntimeError(f"No rebuilt index to switch to for collection {collection_id}")
    alias = _alias(collection_id)
    operations: list[models.AliasOperations] = []
    if _active_physical(collection_id) is not None:
        operations.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
    operations.append(
        models.CreateAliasOperation(create_alias=models.CreateAlias(collection_name=rebuilt, alias_name=alias))
    )
    _client.update_collection_aliases(operations)


# -- collection descriptions ------------------------------------------------------------------------


def _description_text(description: str, tags: Sequence[str]) -> str:
    return " ".join([description, *tags])


def upsert_collection_description(
    collection_id: uuid.UUID, description: str, tags: list[str], embedding: list[float]
) -> None:
    """Full replace of a collection's point (description, tags and both vectors together) - called
    whenever the description itself (and therefore its embedding) changes. For a tags-only change with the
    description unchanged, see update_collection_tags_in_index instead, which doesn't need the embedding."""
    if not _exists(_COLLECTIONS):
        _create_collection(_COLLECTIONS, len(embedding))
    _client.upsert(
        _COLLECTIONS,
        [
            models.PointStruct(
                id=str(collection_id),
                vector={_DENSE: embedding, _SPARSE: _sparse(_description_text(description, tags))},
                payload={"description": description, "tags": tags},
            )
        ],
        wait=True,
    )


def has_collection_description(collection_id: uuid.UUID) -> bool:
    """Whether the collection has its point in the index of the descriptions. False when it cannot be told: the
    caller then writes the point, which is harmless."""
    try:
        return _exists(_COLLECTIONS) and bool(_client.retrieve(_COLLECTIONS, [str(collection_id)], with_vectors=False))
    except Exception:
        logger.exception(f"Failed to look for the description of collection {collection_id} in the index")
        return False


def update_collection_tags_in_index(collection_id: uuid.UUID, tags: list[str]) -> None:
    """Partial update: the tags are searchable text next to the description, so the sparse vector is made
    again, the embedding is left as is - a no-op if the collection has no description embedded yet
    (nothing to merge into; the next description change will index it with these tags anyway)."""
    if not _exists(_COLLECTIONS):
        return
    records = _client.retrieve(_COLLECTIONS, [str(collection_id)], with_payload=["description"], with_vectors=False)
    if not records:
        return
    description = (records[0].payload or {}).get("description", "")
    _client.set_payload(_COLLECTIONS, {"tags": tags}, points=[str(collection_id)], wait=True)
    _client.update_vectors(
        _COLLECTIONS,
        [models.PointVectors(id=str(collection_id), vector={_SPARSE: _sparse(_description_text(description, tags))})],
        wait=True,
    )


def search_collections(
    query: str, query_embedding: list[float], collection_ids: list[uuid.UUID], limit: int
) -> list[tuple[uuid.UUID, float]]:
    """Hybrid search over collection descriptions, restricted to the given candidate ids - the caller
    (SearchService.search_collections) is responsible for that candidate list already being access-filtered;
    this never widens it, only ranks/narrows within it."""
    if not collection_ids:
        return []
    candidates = models.Filter(
        must=[models.HasIdCondition(has_id=[str(collection_id) for collection_id in collection_ids])]
    )
    return _hybrid(_COLLECTIONS, query, query_embedding, limit, candidates)
