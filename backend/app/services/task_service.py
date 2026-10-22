import asyncio
import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import active_task_ids, get_task_status, revoke_tasks
from app.models.document import DocumentStatus
from app.models.task import Task
from app.models.task_log_entry import TaskLogEntry
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.task_log_repository import TaskLogRepository, levels_from
from app.repositories.task_repository import TaskRepository
from app.schemas.pagination import Page, PaginationParams
from app.schemas.task import TaskLogEntryOut, TaskLogsOut, TaskOut

# The most log lines one request returns: a reader behind by more asks again (`has_more`).
LOG_PAGE_SIZE = 500


class TaskNotFoundError(Exception):
    pass


class LogsDocumentNotFoundError(Exception):
    """The document isn't in a collection of the user's own - only its owner sees its tasks."""


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tasks = TaskRepository(db)
        self.logs = TaskLogRepository(db)
        self.documents = DocumentRepository(db)

    async def list_tasks(self, user: RequestContext, pagination: PaginationParams) -> Page[TaskOut]:
        roots, total = await self.tasks.list_root_runs_by_owner(
            user.user_id, limit=pagination.limit, offset=pagination.offset
        )
        descendants = await self.tasks.list_descendants([root.id for root in roots])
        items = [self._to_out(task) for task in [*roots, *descendants]]
        return pagination.to_page(items, total)

    async def revoke(self, task_id: uuid.UUID, user: RequestContext) -> TaskOut:
        """Stops a task and, with it, every task it started (a document's pipeline is a tree: revoking its
        extraction without the hundreds of tasks that follow would stop nothing). Those already over are
        left as they ended. A document that was being processed is then marked as cancelled, not left
        "indexing" for ever."""
        task = await self.tasks.get(task_id, user.user_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        descendants = await self.tasks.list_descendants([task.id])
        tasks = [task, *descendants]
        # Redis is called for each task: off the event loop.
        active = await asyncio.to_thread(active_task_ids, [item.celery_task_id for item in tasks])
        await asyncio.to_thread(revoke_tasks, active)
        await self._cancel_processing(item for item in tasks if item.celery_task_id in active)
        return self._to_out(task, status="REVOKED" if task.celery_task_id in active else None)

    async def _cancel_processing(self, revoked: Iterable[Task]) -> None:
        for document_id in {item.document_id for item in revoked if item.document_id is not None}:
            document = await self.documents.get(document_id)
            if document is not None and document.status in (DocumentStatus.PENDING, DocumentStatus.INDEXING):
                await self.documents.update_status(document, DocumentStatus.ERROR, progress=None, summary=None)
                await self.documents.set_error(document, "Traitement annulé.")
        await self.db.commit()

    async def get_logs(
        self, task_id: uuid.UUID, user: RequestContext, *, after: int = 0, min_level: str | None = None
    ) -> TaskLogsOut:
        task = await self.tasks.get_bare(task_id, user.user_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        entries = await self.logs.list_for_task(
            task.celery_task_id, after=after, levels=levels_from(min_level), limit=LOG_PAGE_SIZE + 1
        )
        return _logs_out(entries)

    async def get_document_logs(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        user: RequestContext,
        *,
        after: int = 0,
        min_level: str | None = None,
    ) -> TaskLogsOut:
        """Every task of a document's pipeline on one timeline - whichever task each line came from."""
        if await CollectionRepository(self.db).get(collection_id, user.user_id) is None:
            raise LogsDocumentNotFoundError(str(collection_id))
        if await DocumentRepository(self.db).get_in_collection(collection_id, document_id) is None:
            raise LogsDocumentNotFoundError(str(document_id))
        entries = await self.logs.list_for_document(
            document_id, after=after, levels=levels_from(min_level), limit=LOG_PAGE_SIZE + 1
        )
        return _logs_out(entries)

    def _to_out(self, task: Task, status: str | None = None) -> TaskOut:
        return TaskOut(
            id=task.id,
            task_name=task.task_name,
            status=status or get_task_status(task.celery_task_id),
            document_id=task.document_id,
            document_name=task.document.name if task.document else None,
            collection_id=task.collection_id,
            collection_name=task.collection.name if task.collection else None,
            parent_id=task.parent_id,
            created_at=task.created_at,
        )


def _logs_out(entries: Sequence[TaskLogEntry]) -> TaskLogsOut:
    """`entries` were fetched one past the page: that one only tells there are more."""
    page = entries[:LOG_PAGE_SIZE]
    return TaskLogsOut(
        entries=[TaskLogEntryOut.model_validate(entry) for entry in page], has_more=len(entries) > LOG_PAGE_SIZE
    )
