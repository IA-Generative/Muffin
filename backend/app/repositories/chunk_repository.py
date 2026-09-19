import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document


class ChunkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count_by_document(self, document_id: uuid.UUID) -> int:
        """The retrieval-evaluation worker's recall@k denominator (see worker/evaluation): with
        no chunk-level relevance judgment available (a QaPair only ever points at a document, not
        a specific chunk - see app/models/qa.py), every chunk of the QA pair's source document is
        treated as a relevant one, the best proxy available without hand-annotated ground truth."""
        return (
            await self.db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)) or 0
        )

    async def get_by_ids(self, chunk_ids: list[uuid.UUID]) -> Sequence[tuple[Chunk, str, uuid.UUID]]:
        """Hydrates the chunk ids a vector search returned (see
        app/services/search_service.py) back into rows with their document name and collection
        id - Meilisearch only ever stores the vector, a lexical copy of the text, and filterable
        metadata; Postgres stays the source of truth for the text itself."""
        if not chunk_ids:
            return []
        stmt = (
            select(Chunk, Document.name, Document.collection_id)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(chunk_ids))
        )
        result = await self.db.execute(stmt)
        return result.all()
