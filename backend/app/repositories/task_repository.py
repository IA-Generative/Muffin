import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        celery_task_id: str,
        task_name: str,
        owner_id: str,
        document_id: uuid.UUID | None = None,
        collection_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            celery_task_id=celery_task_id,
            task_name=task_name,
            owner_id=owner_id,
            document_id=document_id,
            collection_id=collection_id,
            parent_id=parent_id,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def get_by_celery_id(self, celery_task_id: str) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.celery_task_id == celery_task_id))
        return result.scalar_one_or_none()

    async def set_logs(self, task: Task, logs: str) -> None:
        task.logs = logs

    async def list_root_runs_by_owner(self, owner_id: str, *, limit: int, offset: int) -> tuple[Sequence[Task], int]:
        """Paginates over top-level runs (parent_id IS NULL) rather than raw
        rows - a run's children are fetched separately via
        `list_descendants` and always shown in full alongside their root, so
        a page break can never split a run's tree and leave orphaned
        children with no visible parent."""
        where = Task.owner_id == owner_id, Task.parent_id.is_(None)

        total = await self.db.scalar(select(func.count()).select_from(Task).where(*where))

        result = await self.db.execute(
            select(Task)
            .where(*where)
            .options(selectinload(Task.document), selectinload(Task.collection))
            .order_by(Task.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total or 0

    async def list_descendants(self, root_ids: list[uuid.UUID]) -> Sequence[Task]:
        """Walks the parent_id chain outward from `root_ids`, one level per
        query, until a level comes back empty. A handful of round-trips
        beats a recursive CTE here - the tree is only a few levels deep and
        this stays trivial to read."""
        descendants: list[Task] = []
        frontier = set(root_ids)
        seen = set(root_ids)
        while frontier:
            result = await self.db.execute(
                select(Task)
                .where(Task.parent_id.in_(frontier))
                .options(selectinload(Task.document), selectinload(Task.collection))
            )
            rows = [task for task in result.scalars().all() if task.id not in seen]
            if not rows:
                break
            descendants.extend(rows)
            seen.update(task.id for task in rows)
            frontier = {task.id for task in rows}
        return descendants

    async def get(self, task_id: uuid.UUID, owner_id: str) -> Task | None:
        result = await self.db.execute(
            select(Task)
            .where(Task.id == task_id, Task.owner_id == owner_id)
            .options(selectinload(Task.document), selectinload(Task.collection))
        )
        return result.scalar_one_or_none()

    async def get_logs(self, task_id: uuid.UUID, owner_id: str) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
        return result.scalar_one_or_none()
