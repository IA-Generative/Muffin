import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import get_task_status, revoke_task
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.pagination import Page, PaginationParams
from app.schemas.task import TaskLogsOut, TaskOut

LOG_PREVIEW_CHARS = 2000


class TaskNotFoundError(Exception):
    pass


class TaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tasks = TaskRepository(db)

    async def list_tasks(self, user: RequestContext, pagination: PaginationParams) -> Page[TaskOut]:
        roots, total = await self.tasks.list_root_runs_by_owner(
            user.user_id, limit=pagination.limit, offset=pagination.offset
        )
        descendants = await self.tasks.list_descendants([root.id for root in roots])
        items = [self._to_out(task) for task in [*roots, *descendants]]
        return pagination.to_page(items, total)

    async def revoke(self, task_id: uuid.UUID, user: RequestContext) -> TaskOut:
        task = await self.tasks.get(task_id, user.user_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        revoke_task(task.celery_task_id)
        return self._to_out(task)

    async def get_logs(self, task_id: uuid.UUID, user: RequestContext) -> TaskLogsOut:
        task = await self.tasks.get_logs(task_id, user.user_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return TaskLogsOut(id=task.id, logs=task.logs or "")

    def _to_out(self, task: Task) -> TaskOut:
        logs = task.logs or ""
        return TaskOut(
            id=task.id,
            task_name=task.task_name,
            status=get_task_status(task.celery_task_id),
            document_id=task.document_id,
            document_name=task.document.name if task.document else None,
            collection_id=task.collection_id,
            collection_name=task.collection.name if task.collection else None,
            parent_id=task.parent_id,
            created_at=task.created_at,
            # Tail, not head: the most recent lines (including any traceback
            # on failure) are what a card preview should surface first.
            log_preview=logs[-LOG_PREVIEW_CHARS:],
            has_more_logs=len(logs) > LOG_PREVIEW_CHARS,
        )
