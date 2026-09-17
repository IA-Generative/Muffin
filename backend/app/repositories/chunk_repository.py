import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document


class ChunkRepository:
    """No Qdrant/vector store yet (see docs/research-agent-plan.md) - this
    is Postgres full-text search over chunk text, good enough to make
    search_knowledge_base real today without waiting on that infra."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(
        self, collection_ids: list[uuid.UUID], query: str, limit: int
    ) -> Sequence[tuple[Chunk, str, uuid.UUID, float]]:
        tsquery = func.plainto_tsquery("french", query)
        tsvector = func.to_tsvector("french", Chunk.text)
        rank = func.ts_rank(tsvector, tsquery).label("rank")
        stmt = (
            select(Chunk, Document.name, Document.collection_id, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.collection_id.in_(collection_ids))
            .where(tsvector.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.all()
