import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.document import Document, DocumentStatus, DocumentType
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_refresh_repository import DocumentRefreshRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import RefreshScheduleOut

from .collection_service import CollectionNotFoundError
from .document_upload_service import DocumentNotFoundError, DocumentUploadService

# How many documents one scan hands out at most: a backlog (the scan was down for a while) is
# worked through over the next scans instead of flooding the processing queue in one go.
CLAIM_LIMIT = 200


class NotUrlDocumentError(Exception):
    """Only a document added from a URL can be fetched again."""


class DocumentRefreshService:
    """The scheduled refresh of URL documents (#19). The owner sets how often a page is fetched again;
    a periodic scan (worker/document_process, every 30 minutes) claims the documents that are due and
    has each page fetched; the worker reports its content hash. Unchanged, nothing happens but the
    date of the check. Changed, the document is reprocessed from scratch - everything the pipeline
    derived from the old page is replaced."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.documents = DocumentRepository(db)
        self.schedules = DocumentRefreshRepository(db)

    # -- user-facing ------------------------------------------------------------------------------

    async def get_schedule(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> RefreshScheduleOut:
        if await self.collections.get_accessible(collection_id, user.user_id, user.groups) is None:
            raise CollectionNotFoundError(str(collection_id))
        document = await self._document(collection_id, document_id)
        return await self._out(document)

    async def set_schedule(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, interval_minutes: int | None
    ) -> RefreshScheduleOut:
        if await self.collections.get(collection_id, user.user_id) is None:
            raise CollectionNotFoundError(str(collection_id))
        document = await self._document(collection_id, document_id)
        if document.type != DocumentType.URL:
            raise NotUrlDocumentError(str(document_id))
        schedule = await self.schedules.get(document.id)
        if interval_minutes is None:
            if schedule is not None:
                await self.schedules.delete(schedule)
        else:
            next_run_at = datetime.now(UTC) + timedelta(minutes=interval_minutes)
            await self.schedules.set(document.id, interval_minutes, next_run_at)
        await self.db.commit()
        return await self._out(document)

    # -- the worker's side ------------------------------------------------------------------------

    async def claim_due(self) -> list[uuid.UUID]:
        document_ids = await self.schedules.claim_due(datetime.now(UTC), CLAIM_LIMIT)
        await self.db.commit()
        return list(document_ids)

    async def report_fetch(self, document_id: uuid.UUID, content_hash: str) -> bool:
        """The worker fetched the page again. Returns whether it changed - and then the document is
        being reprocessed, for whoever added it (or the collection's owner), whose consumption it is."""
        document = await self.documents.get_with_collection(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        now = datetime.now(UTC)
        # Already being processed (a reindex started since the claim): that run will index the page.
        if document.status in (DocumentStatus.PENDING, DocumentStatus.INDEXING):
            return False
        if document.content_hash == content_hash:
            document.last_fetched_at = now
            await self.db.commit()
            return False
        document.last_fetched_at = now
        await self.db.commit()
        owner_id = document.added_by_user_id or document.collection.owner_id
        await DocumentUploadService(self.db).reprocess(document, owner_id)
        return True

    async def set_content_hash(self, document_id: uuid.UUID, content_hash: str) -> None:
        """The hash of the page as it was just indexed - what the next refresh compares against."""
        document = await self.documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        document.content_hash = content_hash
        document.last_fetched_at = datetime.now(UTC)
        await self.db.commit()

    # -- helpers ----------------------------------------------------------------------------------

    async def _document(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        return document

    async def _out(self, document: Document) -> RefreshScheduleOut:
        schedule = await self.schedules.get(document.id)
        return RefreshScheduleOut(
            interval_minutes=schedule.interval_minutes if schedule else None,
            next_run_at=schedule.next_run_at if schedule else None,
            last_fetched_at=document.last_fetched_at,
        )
