import uuid

from loguru import logger
from meilisearch.errors import MeilisearchApiError

from app.connectors import meilisearch_connector

# Distinguishes a chunk's embedding from a QA pair's question embedding and a document summary's
# embedding, all within the same Meilisearch index (§ QA -> summaries -> chunks retrieval
# cascade) - they all live in chunks_<collection_id> and share the same embedder (all embedded
# with that collection's own embedding_model), only this field says which kind of document it
# is, so search()/search_qa()/search_summaries() below just filter on it.
_KIND_FIELD = "kind"
_KIND_CHUNK = "chunk"
_KIND_QA = "qa"
_KIND_SUMMARY = "summary"

# Stable embedder name used everywhere search/indexing touch a vector - the embedding model's own
# name/version is configured once, on the index's embedder settings at creation time (see
# _create_index), and never appears anywhere in the search path below. Swapping models means a
# new index (blue/green reindex, see issue #12), never renaming this key.
_EMBEDDER = "default"

# Hybrid search blends lexical (full-text) and vector ranking - 1.0 would be pure vector search,
# ignoring the lexical side entirely. 0.5 gives the lexical side an equal say, since the whole
# point of hybrid search is to stop leaving full-text matching on the table.
_SEMANTIC_RATIO = 0.5

_client = meilisearch_connector.client

# Single global index (unlike chunks_<collection_id>, one row per collection here - a
# description isn't chunked) holding every collection's description/tags/embedding, all always
# embedded with the same admin-configured model (see app/services/embedding_model_lookup.py) so
# a query can be compared against every collection's description in one embedding space. Used
# to narrow a large accessible set down to the most relevant candidates before an LLM call
# (§ VDB routing) and, later, to suggest a collection for an uploaded file (§122).
_COLLECTIONS_INDEX = "collections"

# Set once per process, not at import time: enabling this is an HTTP call, and doing it eagerly
# at import would risk crashing app boot if Meilisearch isn't reachable yet (same "must not crash
# boot" reasoning as MeilisearchConnector itself) - deferred here to the first time an index is
# actually about to be created, and re-attempted on every process if it ever failed.
_vector_store_feature_enabled = False


def _ensure_vector_store_feature() -> None:
    global _vector_store_feature_enabled
    if _vector_store_feature_enabled:
        return
    # As of Meilisearch 1.12, embedders/hybrid search are gated behind this experimental flag,
    # settable only through this API (no CLI flag/env var equivalent) - persisted server-side,
    # so this is a one-time no-op after the first successful call, but harmless to repeat.
    #
    # Meilisearch ≥1.13: vectorStore became stable and was removed from experimental-features.
    # The API returns 400 "Unknown field `vectorStore`" — this means the feature is already
    # enabled by default, so we can safely ignore the error and proceed.
    try:
        _client.update_experimental_features({"vectorStore": True})
    except MeilisearchApiError as e:
        if "vectorStore" in str(e):
            logger.info("vectorStore already stable on this Meilisearch version, skipping")
        else:
            raise
    _vector_store_feature_enabled = True


def _index_name(collection_id: uuid.UUID) -> str:
    # One Meilisearch index per Muffin Collection (§7/§12 of the research-agent brief:
    # VDB == Collection in this codebase) - keeps deletion trivial and never mixes
    # vectors from two collections with potentially different embedding models/dimensions.
    return f"chunks_{collection_id}"


def _index_exists(name: str) -> bool:
    try:
        _client.get_index(name)
        return True
    except MeilisearchApiError as error:
        if error.code == "index_not_found":
            return False
        raise


def _create_index(name: str, embedding: list[float]) -> None:
    # Lazily created on first embedding - the embedder's dimensions are whatever the
    # collection's own embedding_model produces, never hardcoded. create_index/update_settings
    # are queued tasks processed in submission order by Meilisearch, so the settings below are
    # guaranteed to apply before any add_documents call made right after this returns - no
    # client-side wait_for_task needed.
    _ensure_vector_store_feature()
    _client.create_index(name, {"primaryKey": "id"})
    _client.index(name).update_settings(
        {
            "embedders": {_EMBEDDER: {"source": "userProvided", "dimensions": len(embedding)}},
            "filterableAttributes": [_KIND_FIELD, "document_id", "collection_id"],
        }
    )


def _upsert(
    collection_id: uuid.UUID,
    point_id: uuid.UUID,
    embedding: list[float],
    kind: str,
    text: str = "",
) -> None:
    name = _index_name(collection_id)
    if not _index_exists(name):
        _create_index(name, embedding)
    _client.index(name).add_documents(
        [
            {
                "id": str(point_id),
                _KIND_FIELD: kind,
                "collection_id": str(collection_id),
                "text": text,
                "_vectors": {_EMBEDDER: embedding},
            }
        ]
    )


def upsert_chunk_embedding(
    collection_id: uuid.UUID,
    chunk_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
) -> None:
    _upsert(collection_id, chunk_id, embedding, _KIND_CHUNK, text)


def upsert_qa_embedding(
    collection_id: uuid.UUID,
    qa_pair_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
) -> None:
    _upsert(collection_id, qa_pair_id, embedding, _KIND_QA, text)


def upsert_summary_embedding(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    embedding: list[float],
    text: str = "",
) -> None:
    _upsert(collection_id, document_id, embedding, _KIND_SUMMARY, text)


def _search(
    collection_id: uuid.UUID,
    query: str,
    query_embedding: list[float],
    limit: int,
    kind_filter: str,
) -> list[tuple[uuid.UUID, float]]:
    name = _index_name(collection_id)
    if not _index_exists(name):
        return []
    result = _client.index(name).search(
        query,
        {
            "vector": query_embedding,
            "hybrid": {"embedder": _EMBEDDER, "semanticRatio": _SEMANTIC_RATIO},
            "filter": kind_filter,
            "limit": limit,
            "showRankingScore": True,
        },
    )
    return [(uuid.UUID(hit["id"]), hit["_rankingScore"]) for hit in result["hits"]]


def search(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _search(collection_id, query, query_embedding, limit, f"{_KIND_FIELD} = {_KIND_CHUNK}")


def search_qa(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _search(collection_id, query, query_embedding, limit, f"{_KIND_FIELD} = {_KIND_QA}")


def search_summaries(
    collection_id: uuid.UUID, query: str, query_embedding: list[float], limit: int
) -> list[tuple[uuid.UUID, float]]:
    return _search(collection_id, query, query_embedding, limit, f"{_KIND_FIELD} = {_KIND_SUMMARY}")


def delete_document_embeddings(collection_id: uuid.UUID, document_id: uuid.UUID, chunk_ids: list[uuid.UUID]) -> None:
    """Best-effort cleanup of every Meilisearch point tied to one document - the chunk
    embeddings (keyed by chunk_id) and the summary embedding (keyed by document_id itself,
    see upsert_summary_embedding). Called from delete_document/reindex_collection *before* the
    Postgres rows go away, so a Meilisearch/network failure here only leaves orphaned vectors
    (never stale references the search path can still hit)."""
    name = _index_name(collection_id)
    if not _index_exists(name):
        return
    try:
        ids = [str(document_id)] + [str(chunk_id) for chunk_id in chunk_ids]
        _client.index(name).delete_documents(ids)
    except Exception:
        logger.exception(f"Failed to delete document {document_id} embeddings from index '{name}'")


def delete_collection(collection_id: uuid.UUID) -> None:
    """Best-effort, same reasoning as app/core/storage.py's delete_objects: called after the
    Collection row is already gone, so a Meilisearch/network failure here must not roll that
    back - it just leaves an orphaned index under a collection id nothing references anymore.
    """
    name = _index_name(collection_id)
    try:
        if _index_exists(name):
            _client.delete_index(name)
    except Exception:
        logger.exception(f"Failed to delete Meilisearch index '{name}' - it is now orphaned")
    try:
        if _index_exists(_COLLECTIONS_INDEX):
            _client.index(_COLLECTIONS_INDEX).delete_document(str(collection_id))
    except Exception:
        logger.exception(f"Failed to remove collection {collection_id} from the '{_COLLECTIONS_INDEX}' index")


def _ensure_collections_index(embedding: list[float]) -> None:
    if _index_exists(_COLLECTIONS_INDEX):
        return
    _ensure_vector_store_feature()
    _client.create_index(_COLLECTIONS_INDEX, {"primaryKey": "id"})
    _client.index(_COLLECTIONS_INDEX).update_settings(
        {
            "embedders": {_EMBEDDER: {"source": "userProvided", "dimensions": len(embedding)}},
            "filterableAttributes": ["id"],
        }
    )


def upsert_collection_description(
    collection_id: uuid.UUID, description: str, tags: list[str], embedding: list[float]
) -> None:
    """Full replace of a collection's row (id/description/tags/embedding together) - called
    whenever the description itself (and therefore its embedding) changes. For a tags-only
    change with the description unchanged, see update_collection_tags_in_index instead, which
    doesn't need to touch the embedding."""
    _ensure_collections_index(embedding)
    _client.index(_COLLECTIONS_INDEX).add_documents(
        [{"id": str(collection_id), "description": description, "tags": tags, "_vectors": {_EMBEDDER: embedding}}]
    )


def update_collection_tags_in_index(collection_id: uuid.UUID, tags: list[str]) -> None:
    """Partial update (Meilisearch merges the given fields into the existing document, it
    doesn't replace it) - a no-op if the collection has no description embedded yet (nothing to
    merge into; the next description change will index it with these tags anyway)."""
    if not _index_exists(_COLLECTIONS_INDEX):
        return
    _client.index(_COLLECTIONS_INDEX).update_documents([{"id": str(collection_id), "tags": tags}])


def search_collections(
    query: str, query_embedding: list[float], collection_ids: list[uuid.UUID], limit: int
) -> list[tuple[uuid.UUID, float]]:
    """Vector (hybrid) search over collection descriptions, restricted to the given candidate
    ids - the caller (SearchService.search_collections) is responsible for that candidate list
    already being access-filtered; this never widens it, only ranks/narrows within it."""
    if not collection_ids or not _index_exists(_COLLECTIONS_INDEX):
        return []
    ids_filter = "id IN [" + ", ".join(f'"{collection_id}"' for collection_id in collection_ids) + "]"
    result = _client.index(_COLLECTIONS_INDEX).search(
        query,
        {
            "vector": query_embedding,
            "hybrid": {"embedder": _EMBEDDER, "semanticRatio": _SEMANTIC_RATIO},
            "filter": ids_filter,
            "limit": limit,
            "showRankingScore": True,
        },
    )
    return [(uuid.UUID(hit["id"]), hit["_rankingScore"]) for hit in result["hits"]]
