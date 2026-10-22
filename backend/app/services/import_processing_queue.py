import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DocumentSettings
from app.core.tasks import PROCESS_DOCUMENT_TASK, enqueue_process_document
from app.models.collection_import import CollectionImport
from app.models.document import Document, DocumentStatus
from app.models.import_document import ImportDocument
from app.repositories.task_repository import TaskRepository

_settings = DocumentSettings()


class ImportProcessingQueue:
    """The documents of a ZIP import waiting for their turn to be extracted (#335).

    An import registers its documents as the worker stores them, which used to queue the processing of
    each one at once: an archive of 2000 files filled the queue, whatever the pod could do. Now a document
    is queued - still with the low priority of an import - only when its import has room:
    IMPORT_PROCESSING_WINDOW of its documents being extracted at a time. The end of an extraction, an
    error, a cancellation or a deletion frees a place and releases the next one; a periodic sweep
    (`release_waiting`) catches whatever none of them did.

    What counts as being extracted is derived, never kept in step: a document released, whose extraction
    has not ended, that is still pending or indexing, and was released less than
    IMPORT_SLOT_TIMEOUT_SECONDS ago. An errored or deleted document stops counting by itself."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tasks = TaskRepository(db)

    async def add(self, import_id: uuid.UUID, document_id: uuid.UUID) -> None:
        """The document waits for its turn - call `release` once it is committed."""
        self.db.add(ImportDocument(import_id=import_id, document_id=document_id))
        await self.db.flush()

    async def release(self, import_id: uuid.UUID) -> int:
        """Queues the documents of the import that fit in its window, the oldest first. Returns how many.
        The import's row is locked while the places are counted and handed out, so that two ends of
        extraction at the same time do not release the same document, nor more than the window."""
        collection_import = await self.db.get(CollectionImport, import_id, with_for_update=True, populate_existing=True)
        if collection_import is None:
            await self.db.rollback()
            return 0
        free = max(_settings.IMPORT_PROCESSING_WINDOW, 1) - await self._extracting(import_id)
        released: list[tuple[uuid.UUID, uuid.UUID]] = []
        if free > 0:
            rows = await self.db.execute(
                select(ImportDocument, Document.collection_id)
                .join(Document, Document.id == ImportDocument.document_id)
                .where(ImportDocument.import_id == import_id, ImportDocument.released_at.is_(None))
                .order_by(ImportDocument.created_at, ImportDocument.document_id)
                .limit(free)
                .with_for_update(of=ImportDocument, skip_locked=True)
            )
            now = datetime.now(UTC)
            for entry, collection_id in rows.all():
                entry.released_at = now
                released.append((entry.document_id, collection_id))
        owner_id = collection_import.owner_id
        await self.db.commit()
        queued = 0
        try:
            for document_id, collection_id in released:
                # Redis is called off the event loop.
                celery_task_id = await asyncio.to_thread(enqueue_process_document, str(document_id), bulk=True)
                await self.tasks.create(
                    celery_task_id,
                    PROCESS_DOCUMENT_TASK,
                    owner_id,
                    document_id=document_id,
                    collection_id=collection_id,
                )
                await self.db.commit()
                queued += 1
        except Exception:
            # What was not queued waits again, rather than holding a place it does not use.
            logger.exception(f"Could not queue the processing of the documents of import {import_id}")
            await self.db.rollback()
            for document_id, _ in released[queued:]:
                entry = await self.db.get(ImportDocument, document_id)
                if entry is not None:
                    entry.released_at = None
            await self.db.commit()
            raise
        if released:
            logger.info(f"Import {import_id}: {len(released)} document(s) released for extraction")
        return len(released)

    async def finish(self, document_id: uuid.UUID) -> None:
        """The document's extraction ended, or it will never be: its place goes to the next one of its
        import. A document of no import - a plain upload - does nothing."""
        entry = await self.db.get(ImportDocument, document_id)
        if entry is None:
            return
        import_id = entry.import_id
        if entry.extraction_done_at is None:
            entry.extraction_done_at = datetime.now(UTC)
        await self.db.commit()
        await self.release(import_id)

    async def requeue(self, document_id: uuid.UUID) -> uuid.UUID | None:
        """A document of an import that is processed again waits for its turn in the window like the first
        time: returns its import, or None for a document of no import. Not committed - call `release` once
        it is."""
        entry = await self.db.get(ImportDocument, document_id)
        if entry is None:
            return None
        entry.released_at = None
        entry.extraction_done_at = None
        await self.db.flush()
        return entry.import_id

    async def import_of(self, document_id: uuid.UUID) -> uuid.UUID | None:
        """The import a document belongs to - asked before the document is deleted, which erases it."""
        entry = await self.db.get(ImportDocument, document_id)
        return entry.import_id if entry is not None else None

    async def release_waiting(self) -> int:
        """The sweep: for each import with a document waiting, releases what its window allows."""
        result = await self.db.execute(
            select(ImportDocument.import_id).where(ImportDocument.released_at.is_(None)).distinct()
        )
        released = 0
        for import_id in result.scalars().all():
            released += await self.release(import_id)
        return released

    async def _extracting(self, import_id: uuid.UUID) -> int:
        since = datetime.now(UTC) - timedelta(seconds=_settings.IMPORT_SLOT_TIMEOUT_SECONDS)
        count = await self.db.scalar(
            select(func.count())
            .select_from(ImportDocument)
            .join(Document, Document.id == ImportDocument.document_id)
            .where(
                ImportDocument.import_id == import_id,
                ImportDocument.released_at.is_not(None),
                ImportDocument.released_at > since,
                ImportDocument.extraction_done_at.is_(None),
                Document.status.in_((DocumentStatus.PENDING, DocumentStatus.INDEXING)),
            )
        )
        return count or 0
