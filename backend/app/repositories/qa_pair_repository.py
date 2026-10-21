import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.qa import QaOrigin, QaPair


class QaPairRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID | None,
        question: str,
        answer: str,
        source_page: int | None = None,
        source_excerpt: str | None = None,
        generation_key: str | None = None,
    ) -> QaPair:
        qa_pair = QaPair(
            collection_id=collection_id,
            document_id=document_id,
            question=question,
            answer=answer,
            origin=QaOrigin.GENERATED,
            generation_key=generation_key,
            source_page=source_page,
            source_excerpt=source_excerpt,
        )
        self.db.add(qa_pair)
        await self.db.flush()
        return qa_pair

    async def list_generated_windows(self, document_id: uuid.UUID) -> list[QaPair]:
        """The pairs the pipeline generated from the windows of a document's pages and nobody touched:
        what another document of the same file reuses (#300). Not the ones a person validated, which are
        their work and belong to their collection."""
        result = await self.db.execute(
            select(QaPair).where(
                QaPair.document_id == document_id,
                QaPair.origin == QaOrigin.GENERATED,
                QaPair.validated.is_(False),
                QaPair.generation_key.like("window:%"),
            )
        )
        return list(result.scalars().all())

    async def delete_generated_run(
        self, collection_id: uuid.UUID, document_id: uuid.UUID | None, generation_key: str
    ) -> list[uuid.UUID]:
        """Removes what a previous run of the pipeline generated under this key (#299), so that the run
        replaces its pairs instead of adding a second set. A pair a person has validated stays: the
        work of a person is not thrown away by a task running again. Returns the removed ids, whose
        vectors are still to remove."""
        result = await self.db.execute(
            delete(QaPair)
            .where(
                QaPair.collection_id == collection_id,
                QaPair.document_id.is_(None) if document_id is None else QaPair.document_id == document_id,
                QaPair.generation_key == generation_key,
                QaPair.origin == QaOrigin.GENERATED,
                QaPair.validated.is_(False),
            )
            .returning(QaPair.id)
        )
        return list(result.scalars().all())

    async def delete_generated_for_document(
        self, document_id: uuid.UUID, *, keep_validated: bool
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Removes every pair the pipeline generated from a document: they answer from its content and
        go with it - when it is deleted, or reprocessed (which regenerates them). `keep_validated`
        keeps the ones a person validated, for a reprocess; a deleted document keeps none, since what
        they were grounded in is gone. Returns (collection id, pair id) of the removed ones."""
        condition = [QaPair.document_id == document_id, QaPair.origin == QaOrigin.GENERATED]
        if keep_validated:
            condition.append(QaPair.validated.is_(False))
        result = await self.db.execute(delete(QaPair).where(*condition).returning(QaPair.collection_id, QaPair.id))
        return [(row.collection_id, row.id) for row in result.all()]

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

    async def random_with_source(
        self, collection_ids: Sequence[uuid.UUID], *, validated: bool | None, limit: int, exclude: Sequence[uuid.UUID]
    ) -> Sequence[QaPair]:
        """Random generated or written pairs that have a document to cite (#126), never a golden one.
        `validated` narrows to the reviewed ones (True) or the others (False); None takes any."""
        if not collection_ids or limit <= 0:
            return []
        where = [
            QaPair.collection_id.in_(collection_ids),
            QaPair.golden.is_(False),
            QaPair.document_id.is_not(None),
            QaPair.id.not_in(exclude) if exclude else true(),
        ]
        if validated is not None:
            where.append(QaPair.validated.is_(validated))
        result = await self.db.execute(
            select(QaPair).where(*where).options(selectinload(QaPair.document)).order_by(func.random()).limit(limit)
        )
        return result.scalars().all()

    async def get_with_document(self, qa_pair_id: uuid.UUID) -> QaPair | None:
        result = await self.db.execute(
            select(QaPair)
            .where(QaPair.id == qa_pair_id, QaPair.golden.is_(False))
            .options(selectinload(QaPair.document))
        )
        return result.scalar_one_or_none()
