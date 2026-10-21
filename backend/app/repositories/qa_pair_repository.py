import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document
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

    async def create_manual(
        self,
        collection_id: uuid.UUID,
        question: str,
        answer: str,
        document_ids: list[uuid.UUID],
        *,
        golden: bool,
    ) -> QaPair:
        """A pair a person wrote, so validated. A golden one (#260) is a test question that is never
        embedded; only it keeps the full list of relevant documents. The main document is the first,
        which is what the rest of the code reads."""
        qa_pair = QaPair(
            collection_id=collection_id,
            document_id=document_ids[0] if document_ids else None,
            question=question,
            answer=answer,
            origin=QaOrigin.MANUAL,
            validated=True,
            golden=golden,
            relevant_document_ids=[str(document_id) for document_id in document_ids] or None if golden else None,
        )
        self.db.add(qa_pair)
        await self.db.flush()
        return qa_pair

    async def get_in_collection(self, collection_id: uuid.UUID, qa_pair_id: uuid.UUID) -> QaPair | None:
        result = await self.db.execute(
            select(QaPair).where(QaPair.id == qa_pair_id, QaPair.collection_id == collection_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, qa_pair: QaPair) -> None:
        await self.db.delete(qa_pair)
        await self.db.flush()

    async def document_names(self, collection_id: uuid.UUID, document_ids: Sequence[uuid.UUID]) -> dict[str, str]:
        """Names of the given documents, by id - only those in this collection, so an id from
        elsewhere is simply absent (which is how a golden pair's relevant documents are checked)."""
        if not document_ids:
            return {}
        result = await self.db.execute(
            select(Document.id, Document.name).where(
                Document.collection_id == collection_id, Document.id.in_(document_ids)
            )
        )
        return {str(document_id): name for document_id, name in result.all()}

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

    async def get_by_ids(self, qa_pair_ids: list[uuid.UUID]) -> Sequence[QaPair]:
        if not qa_pair_ids:
            return []
        # Never a golden pair: it is not in the retriever, and nothing that answers may use one even
        # if a stray vector pointed at it.
        result = await self.db.execute(select(QaPair).where(QaPair.id.in_(qa_pair_ids), QaPair.golden.is_(False)))
        return result.scalars().all()
