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

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[QaPair]:
        result = await self.db.execute(
            select(QaPair)
            .where(QaPair.collection_id == collection_id)
            .options(selectinload(QaPair.document))
            .order_by(QaPair.created_at.desc())
        )
        return result.scalars().all()
