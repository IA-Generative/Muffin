import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document
from app.models.index_rebuild import ACTIVE_REBUILD_STATUSES, IndexRebuild
from app.models.qa import QaPair


class IndexRebuildRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, rebuild_id: uuid.UUID) -> IndexRebuild | None:
        return await self.db.get(IndexRebuild, rebuild_id)

    async def get_active(self, collection_id: uuid.UUID) -> IndexRebuild | None:
        result = await self.db.execute(
            select(IndexRebuild).where(
                IndexRebuild.collection_id == collection_id, IndexRebuild.status.in_(ACTIVE_REBUILD_STATUSES)
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(self, collection_id: uuid.UUID) -> IndexRebuild | None:
        result = await self.db.execute(
            select(IndexRebuild)
            .where(IndexRebuild.collection_id == collection_id)
            .order_by(IndexRebuild.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add(self, rebuild: IndexRebuild) -> IndexRebuild:
        self.db.add(rebuild)
        await self.db.flush()
        return rebuild

    async def expected_points(self, collection_id: uuid.UUID) -> dict[str, tuple[str, str]]:
        """Every point the collection's index must hold, from PostgreSQL - the source of truth - by id:
        (kind, text). The chunks, each document's summary, and the QA pairs that answer (never a
        golden one, #260)."""
        points: dict[str, tuple[str, str]] = {}
        chunks = await self.db.execute(
            select(Chunk.id, Chunk.text)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.collection_id == collection_id)
        )
        points.update({str(point_id): ("chunk", text) for point_id, text in chunks.all()})
        summaries = await self.db.execute(
            select(Document.id, Document.summary).where(
                Document.collection_id == collection_id, Document.summary.is_not(None), Document.summary != ""
            )
        )
        points.update({str(point_id): ("summary", text) for point_id, text in summaries.all()})
        qa_pairs = await self.db.execute(
            select(QaPair.id, QaPair.question).where(QaPair.collection_id == collection_id, QaPair.golden.is_(False))
        )
        points.update({str(point_id): ("qa", text) for point_id, text in qa_pairs.all()})
        return points

    async def current_texts(self, point_ids: Sequence[uuid.UUID]) -> dict[str, str]:
        """The text each point has now, whatever its kind - to refuse a vector made from an older one."""
        if not point_ids:
            return {}
        texts: dict[str, str] = {}
        for column_id, column_text in (
            (Chunk.id, Chunk.text),
            (Document.id, Document.summary),
            (QaPair.id, QaPair.question),
        ):
            rows = await self.db.execute(select(column_id, column_text).where(column_id.in_(point_ids)))
            texts.update({str(point_id): text for point_id, text in rows.all() if text})
        return texts
