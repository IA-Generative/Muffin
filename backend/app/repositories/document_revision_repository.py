import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_revision import DocumentRevision, RevisionOrigin


class DocumentRevisionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_document(self, document_id: uuid.UUID) -> Sequence[DocumentRevision]:
        result = await self.db.execute(
            select(DocumentRevision)
            .where(DocumentRevision.document_id == document_id)
            .order_by(DocumentRevision.number.desc())
        )
        return result.scalars().all()

    async def get_by_number(self, document_id: uuid.UUID, number: int) -> DocumentRevision | None:
        result = await self.db.execute(
            select(DocumentRevision).where(
                DocumentRevision.document_id == document_id, DocumentRevision.number == number
            )
        )
        return result.scalar_one_or_none()

    async def current_number(self, document_id: uuid.UUID) -> int | None:
        return await self.db.scalar(
            select(func.max(DocumentRevision.number)).where(DocumentRevision.document_id == document_id)
        )

    async def list_storage_keys(self, document_id: uuid.UUID) -> list[str]:
        result = await self.db.scalars(
            select(DocumentRevision.storage_key).where(DocumentRevision.document_id == document_id)
        )
        return list(result.all())

    async def create(
        self,
        document_id: uuid.UUID,
        *,
        storage_key: str,
        filename: str,
        format_: str,
        origin: RevisionOrigin,
        created_by_user_id: str | None,
        created_by_display: str | None,
        restored_from_number: int | None = None,
    ) -> DocumentRevision:
        """Appends a revision numbered max+1. Two concurrent writers would both compute the same
        number and the unique (document_id, number) constraint rejects the second - the soft lock
        that prevents that situation up front is #170."""
        number = (await self.current_number(document_id) or 0) + 1
        revision = DocumentRevision(
            document_id=document_id,
            number=number,
            storage_key=storage_key,
            filename=filename,
            format=format_,
            origin=origin,
            created_by_user_id=created_by_user_id,
            created_by_display=created_by_display,
            restored_from_number=restored_from_number,
        )
        self.db.add(revision)
        await self.db.flush()
        return revision
