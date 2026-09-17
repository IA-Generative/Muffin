import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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
