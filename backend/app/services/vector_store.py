import uuid

from loguru import logger
from qdrant_client import models as qdrant_models

from app.connectors import qdrant_connector


def _collection_name(collection_id: uuid.UUID) -> str:
    # One Qdrant collection per Muffin Collection (§7/§12 of the research-agent brief:
    # VDB == Collection in this codebase) - keeps deletion trivial and never mixes
    # vectors from two collections with potentially different embedding models/dimensions.
    return f"chunks_{collection_id}"


def upsert_chunk_embedding(collection_id: uuid.UUID, chunk_id: uuid.UUID, embedding: list[float]) -> None:
    name = _collection_name(collection_id)
    if not qdrant_connector.client.collection_exists(name):
        # Lazily created on first embedding - the vector size is whatever the
        # collection's own embedding_model produces, never hardcoded.
        qdrant_connector.client.create_collection(
            collection_name=name,
            vectors_config=qdrant_models.VectorParams(size=len(embedding), distance=qdrant_models.Distance.COSINE),
        )
    qdrant_connector.client.upsert(
        collection_name=name,
        points=[qdrant_models.PointStruct(id=str(chunk_id), vector=embedding)],
    )


def search(collection_id: uuid.UUID, query_embedding: list[float], limit: int) -> list[tuple[uuid.UUID, float]]:
    name = _collection_name(collection_id)
    if not qdrant_connector.client.collection_exists(name):
        return []
    hits = qdrant_connector.client.query_points(collection_name=name, query=query_embedding, limit=limit).points
    return [(uuid.UUID(str(hit.id)), hit.score) for hit in hits]


def delete_collection(collection_id: uuid.UUID) -> None:
    """Best-effort, same reasoning as app/core/storage.py's delete_objects: called after the
    Collection row is already gone, so a Qdrant/network failure here must not roll that back -
    it just leaves orphaned vectors under a collection id nothing references anymore."""
    name = _collection_name(collection_id)
    try:
        if qdrant_connector.client.collection_exists(name):
            qdrant_connector.client.delete_collection(name)
    except Exception:
        logger.exception(f"Failed to delete Qdrant collection '{name}' - it is now orphaned")
