import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.qa import QaOrigin, QaPair


class QaPairRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self, collection_id: uuid.UUID, document_id: uuid.UUID | None, question: str, answer: str
    ) -> QaPair:
        qa_pair = QaPair(
            collection_id=collection_id,
            document_id=document_id,
            question=question,
            answer=answer,
            origin=QaOrigin.GENERATED,
        )
        self.db.add(qa_pair)
        await self.db.flush()
        return qa_pair

    async def list_by_collection(
        self, collection_id: uuid.UUID, document_id: uuid.UUID | None = None
    ) -> Sequence[QaPair]:
        where = [QaPair.collection_id == collection_id]
        if document_id is not None:
            where.append(QaPair.document_id == document_id)
        result = await self.db.execute(
            select(QaPair).where(*where).options(selectinload(QaPair.document)).order_by(QaPair.created_at.desc())
        )
        return result.scalars().all()

    async def list_validated_by_collection(self, collection_id: uuid.UUID) -> Sequence[QaPair]:
        """What worker/evaluation replays retrieval against (see #11) - only ever the pairs a
        human has actually validated, never the raw generated set (unreviewed ones may be wrong,
        which would make the evaluation itself unreliable)."""
        result = await self.db.execute(
            select(QaPair)
            .where(QaPair.collection_id == collection_id, QaPair.validated.is_(True))
            .order_by(QaPair.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_ids(self, qa_pair_ids: list[uuid.UUID]) -> Sequence[QaPair]:
        if not qa_pair_ids:
            return []
        result = await self.db.execute(select(QaPair).where(QaPair.id.in_(qa_pair_ids)))
        return result.scalars().all()
