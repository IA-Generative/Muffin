import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_stage import DocumentStage

# The piece a stage that is not run in pieces is done with.
WHOLE = "_"


class DocumentStageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def begin(self, document_id: uuid.UUID, stage: str, fingerprint: str, expected: list[str]) -> DocumentStage:
        """The stage starts again for this document, whatever it had recorded: not done, not copied from
        anywhere. Locked, as the pieces of a stage finish concurrently (see mark_done)."""
        row = await self._locked(document_id, stage)
        if row is None:
            row = DocumentStage(document_id=document_id, stage=stage)
            self.db.add(row)
        row.fingerprint = fingerprint
        row.expected = list(expected)
        row.done = []
        row.source_document_id = None
        row.completed_at = None
        await self.db.flush()
        return row

    async def mark_done(self, document_id: uuid.UUID, stage: str, key: str = WHOLE) -> bool:
        """A piece of the stage is done; the stage is complete once every piece it announced is. A
        stage nobody began (the worker could not fingerprint it) is left alone. Locked: the pieces are
        tasks finishing at the same time, and a read-modify-write of the list would lose one."""
        row = await self._locked(document_id, stage)
        if row is None:
            return False
        if key not in row.done:
            row.done = [*row.done, key]
        required = set(row.expected) or {WHOLE}
        if row.completed_at is None and required <= set(row.done):
            row.completed_at = datetime.now(UTC)
        await self.db.flush()
        return row.completed_at is not None

    async def complete(self, row: DocumentStage, source_document_id: uuid.UUID) -> None:
        """The stage was copied from another document, whole."""
        row.done = sorted(set(row.expected) or {WHOLE})
        row.source_document_id = source_document_id
        row.completed_at = datetime.now(UTC)
        await self.db.flush()

    async def find_source(
        self, stage: str, fingerprint: str, content_hash: str, excluding: uuid.UUID
    ) -> Document | None:
        """A document of the same file whose stage is complete under the same fingerprint, in any
        collection - the latest, whose results are the most likely to reflect today's code."""
        result = await self.db.execute(
            select(Document)
            .join(DocumentStage, DocumentStage.document_id == Document.id)
            .where(
                DocumentStage.stage == stage,
                DocumentStage.fingerprint == fingerprint,
                DocumentStage.completed_at.is_not(None),
                Document.content_hash == content_hash,
                Document.id != excluding,
            )
            .order_by(DocumentStage.completed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_for_document(self, document_id: uuid.UUID) -> None:
        """What a document derived is gone (it is reprocessed, moved): so is the record of having done it,
        or another document would copy what is not there anymore."""
        await self.db.execute(delete(DocumentStage).where(DocumentStage.document_id == document_id))

    async def _locked(self, document_id: uuid.UUID, stage: str) -> DocumentStage | None:
        result = await self.db.execute(
            select(DocumentStage)
            .where(DocumentStage.document_id == document_id, DocumentStage.stage == stage)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
