import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.collection_repository import CollectionRepository
from app.services.search_service import embed_text


async def vector_for_active_index(
    db: AsyncSession, collection_id: uuid.UUID, text: str, embedding: list[float], model: str | None
) -> tuple[list[float] | None, str]:
    """The vector to store in the collection's active index, and the model it was made with.

    The worker sends the model it used; when it isn't the index's - the index was rebuilt with a new
    model (#12) between the worker reading the collection's settings and this write - the vector is
    made again with the index's model, so the index never mixes two models. None when that fails:
    the point is then left out (the next rebuild adds it), rather than stored wrong."""
    active = (await CollectionRepository(db).get_embedding_models([collection_id]))[collection_id]
    if model is None or model == active:
        return embedding, active
    try:
        return await embed_text(active, text), active
    except Exception:
        logger.exception(f"Failed to embed a point again with {active} for collection {collection_id}")
        return None, active
