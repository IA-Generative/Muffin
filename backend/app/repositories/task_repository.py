import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import TERMINAL_TASK_STATUSES, Task, TaskStatus


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
        conversation_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            celery_task_id=celery_task_id,
            task_name=task_name,
            owner_id=owner_id,
            document_id=document_id,
            collection_id=collection_id,
            conversation_id=conversation_id,
            parent_id=parent_id,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def set_status(self, celery_task_id: str, status: TaskStatus, error: str | None = None) -> None:
        """Records what the worker reported (see app/routers/internal_tasks.py's status endpoint).
        A task already REVOKED stays so: a worker that finishes after the user revoked it must not
        overwrite the revocation."""
        values: dict[str, Any] = {"status": status}
        if status is TaskStatus.STARTED:
            # A retry starts the task again: keep the first start, it is when it really began.
            values["started_at"] = func.coalesce(Task.started_at, func.now())
        elif status in TERMINAL_TASK_STATUSES:
            values["finished_at"] = func.now()
            values["error"] = error
        where = [Task.celery_task_id == celery_task_id]
        if status is not TaskStatus.REVOKED:
            where.append(Task.status != TaskStatus.REVOKED)
        await self.db.execute(update(Task).where(*where).values(**values))

    async def mark_revoked(self, celery_task_ids: Sequence[str]) -> None:
        """The tasks the backend just revoked, so their status says so without waiting for a
        worker that may never report (one still waiting in the queue, or whose pod is gone)."""
        if not celery_task_ids:
            return
        await self.db.execute(
            update(Task)
            .where(Task.celery_task_id.in_(celery_task_ids))
            .values(status=TaskStatus.REVOKED, finished_at=func.now())
        )

    async def reap_stuck(self, before: datetime) -> int:
        """Marks the tasks still STARTED since before `before` as failed: their worker died and
        Celery will not report them (see the beat's reap_stuck_tasks). A task that is genuinely
        long is left alone - the timeout is well past the workers' own limits."""
        result = await self.db.execute(
            update(Task)
            .where(Task.status == TaskStatus.STARTED, Task.started_at < before)
            .values(
                status=TaskStatus.FAILURE,
                finished_at=func.now(),
                error="Task lost: no result after its timeout",
            )
        )
        return result.rowcount or 0

    async def list_for_document(self, document_id: uuid.UUID) -> Sequence[Task]:
        result = await self.db.execute(select(Task).where(Task.document_id == document_id))
        return result.scalars().all()

    async def get_by_celery_id(self, celery_task_id: str) -> Task | None:
        result = await self.db.execute(select(Task).where(Task.celery_task_id == celery_task_id))
        return result.scalar_one_or_none()

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

    async def get_bare(self, task_id: uuid.UUID, owner_id: str) -> Task | None:
        """`get` without the document and the collection, for when only the task itself is needed."""
        result = await self.db.execute(select(Task).where(Task.id == task_id, Task.owner_id == owner_id))
        return result.scalar_one_or_none()
