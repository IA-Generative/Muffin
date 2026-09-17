import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document


class ChunkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_ids(self, chunk_ids: list[uuid.UUID]) -> Sequence[tuple[Chunk, str, uuid.UUID]]:
        """Hydrates the chunk ids a vector search returned (see
        app/services/search_service.py) back into rows with their document name and
        collection id - Qdrant only ever stores the vector + point id, never the text."""
        if not chunk_ids:
            return []
        stmt = (
            select(Chunk, Document.name, Document.collection_id)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(chunk_ids))
        )
        result = await self.db.execute(stmt)
        return result.all()
