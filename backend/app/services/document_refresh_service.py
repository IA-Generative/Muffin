import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import REFRESH_URL_DOCUMENT_TASK, enqueue_refresh_url_document
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_refresh_schedule import SCAN_MINUTES, DocumentRefreshSchedule, RefreshKind
from app.models.task import TaskStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_refresh_repository import DocumentRefreshRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.document import RefreshSchedule, RefreshScheduleOut
from app.services.copied_collections import ensure_not_copied

from .collection_service import CollectionNotFoundError
from .document_upload_service import DocumentNotFoundError, DocumentUploadService

# How many documents one scan hands out at most: a backlog (the scan was down for a while) is
# worked through over the next scans instead of flooding the processing queue in one go.
CLAIM_LIMIT = 200


class NotUrlDocumentError(Exception):
    """Only a document added from a URL can be fetched again."""


class DocumentBeingProcessedError(Exception):
    """The document is being processed: that run fetches the page already."""


def _next_slot(moment: datetime) -> datetime:
    """The first time the scan runs at or after `moment` - on the hour or at half past."""
    slot = moment.replace(minute=moment.minute - moment.minute % SCAN_MINUTES, second=0, microsecond=0)
    return slot if slot >= moment else slot + timedelta(minutes=SCAN_MINUTES)


def first_run(schedule: RefreshSchedule, now: datetime) -> datetime:
    """When a schedule just set runs first."""
    if schedule.kind == RefreshKind.ONCE:
        return schedule.run_at.astimezone(UTC)
    if schedule.kind == RefreshKind.INTERVAL:
        return _next_slot(now + timedelta(minutes=schedule.interval_minutes))
    return _next_at_time_of_day(schedule, now)


def next_run(schedule: DocumentRefreshSchedule, now: datetime) -> datetime | None:
    """When a schedule that just ran runs next - None for a single fetch, which is done."""
    if schedule.kind == RefreshKind.ONCE:
        return None
    if schedule.kind == RefreshKind.INTERVAL:
        # Counted from the previous run, not from when the scan got to it: no drift. Runs missed while
        # the scan was down are skipped, not caught up one after the other.
        interval = timedelta(minutes=schedule.interval_minutes)
        return schedule.next_run_at + interval * ((now - schedule.next_run_at) // interval + 1)
    return _next_at_time_of_day(schedule, now)


def _next_at_time_of_day(schedule: RefreshSchedule | DocumentRefreshSchedule, now: datetime) -> datetime:
    """The first day (any, or one of the weekdays) whose time_of_day, in the owner's time zone, is
    after `now` - so 9:00 stays 9:00 across daylight saving changes."""
    zone = ZoneInfo(schedule.timezone)
    today = now.astimezone(zone).date()
    for offset in range(8):
        day = today + timedelta(days=offset)
        if schedule.kind == RefreshKind.WEEKLY and day.weekday() not in schedule.weekdays:
            continue
        candidate = datetime.combine(day, schedule.time_of_day, tzinfo=zone).astimezone(UTC)
        if candidate > now:
            return candidate
    raise ValueError("a weekly schedule without any day")  # the schema refuses one


class DocumentRefreshService:
    """The scheduled refresh of URL documents (#19). The owner sets when a page is fetched again;
    a periodic scan (worker/document_process, on the hour and at half past) claims the documents due and
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
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        refresh_schedule: RefreshSchedule | None,
    ) -> RefreshScheduleOut:
        if (collection := await self.collections.get(collection_id, user.user_id)) is None:
            raise CollectionNotFoundError(str(collection_id))
        ensure_not_copied(collection)
        document = await self._document(collection_id, document_id)
        if document.type != DocumentType.URL:
            raise NotUrlDocumentError(str(document_id))
        await self.apply(document.id, refresh_schedule)
        await self.db.commit()
        return await self._out(document)

    async def refresh_now(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> uuid.UUID:
        """Fetches the page now, whatever its schedule (which goes on unchanged): the same check as a
        scheduled one - reprocessed if the page changed, only its date of last fetch otherwise. Returns
        the id of the task, which the user follows in their tasks, logs included."""
        if (collection := await self.collections.get(collection_id, user.user_id)) is None:
            raise CollectionNotFoundError(str(collection_id))
        ensure_not_copied(collection)
        document = await self._document(collection_id, document_id)
        if document.type != DocumentType.URL:
            raise NotUrlDocumentError(str(document_id))
        if document.status in (DocumentStatus.PENDING, DocumentStatus.INDEXING):
            raise DocumentBeingProcessedError(str(document_id))
        tasks = TaskRepository(self.db)
        task_id = str(uuid.uuid4())
        task = await tasks.create(
            task_id,
            REFRESH_URL_DOCUMENT_TASK,
            user.user_id,
            document_id=document.id,
            collection_id=collection_id,
        )
        await self.db.commit()
        try:
            result_id = enqueue_refresh_url_document(str(document.id), task_id=task_id)
        except Exception as exc:
            await tasks.set_status(task_id, TaskStatus.FAILURE, str(exc))
            await self.db.commit()
            raise
        await tasks.rename_celery_task_id(task_id, result_id)
        await self.db.commit()
        return task.id

    async def apply(self, document_id: uuid.UUID, refresh_schedule: RefreshSchedule | None) -> None:
        """Sets (or, with None, removes) a URL document's schedule - also when the URL is added.
        Doesn't commit."""
        if refresh_schedule is None:
            schedule = await self.schedules.get(document_id)
            if schedule is not None:
                await self.schedules.delete(schedule)
            return
        await self.schedules.set(document_id, refresh_schedule, first_run(refresh_schedule, datetime.now(UTC)))

    # -- the worker's side ------------------------------------------------------------------------

    async def claim_due(self) -> list[uuid.UUID]:
        """The documents due, each claimed once: its next run moves forward in the same transaction,
        or, for a single fetch, its schedule goes away."""
        now = datetime.now(UTC)
        schedules = await self.schedules.claim_due(now, CLAIM_LIMIT)
        for schedule in schedules:
            following = next_run(schedule, now)
            if following is None:
                await self.schedules.delete(schedule)
            else:
                schedule.next_run_at = following
        await self.db.commit()
        return [schedule.document_id for schedule in schedules]

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

    async def set_content_hash(self, document_id: uuid.UUID, content_hash: str, storage_key: str | None) -> None:
        """The hash of the page as it was just indexed - what the next refresh compares against. For a
        URL serving a file, also where the worker stored it: processed like an upload from there, and
        deleted with the document."""
        document = await self.documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if storage_key is not None:
            # The same layout as an upload, in this document's own collection.
            if not storage_key.startswith(f"documents/{document.collection_id}/"):
                raise ValueError(f"storage_key outside the document's collection: {storage_key}")
            document.storage_key = storage_key
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
        if schedule is None:
            return RefreshScheduleOut(schedule=None, next_run_at=None, last_fetched_at=document.last_fetched_at)
        return RefreshScheduleOut(
            schedule=RefreshSchedule.model_construct(
                kind=schedule.kind.value,
                # A single fetch's date is its next run.
                run_at=schedule.next_run_at if schedule.kind == RefreshKind.ONCE else None,
                time_of_day=schedule.time_of_day,
                weekdays=schedule.weekdays,
                interval_minutes=schedule.interval_minutes,
                timezone=schedule.timezone,
            ),
            next_run_at=schedule.next_run_at,
            last_fetched_at=document.last_fetched_at,
        )
