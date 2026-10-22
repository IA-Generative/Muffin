import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_log_entry import TaskLogEntry

# loguru's levels, lowest first: filtering on one keeps it and those after it.
LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")


def levels_from(min_level: str | None) -> tuple[str, ...] | None:
    """The levels at or above `min_level` - None, no filter, for no level or one loguru doesn't have."""
    if min_level is None or min_level.upper() not in LEVELS:
        return None
    return LEVELS[LEVELS.index(min_level.upper()) :]


class TaskLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(self, entries: list[dict[str, Any]]) -> None:
        """One INSERT for a whole batch - a worker sends its lines a few dozen at a time."""
        if entries:
            await self.db.execute(insert(TaskLogEntry), entries)

    async def list_for_task(
        self, celery_task_id: str, *, after: int, levels: tuple[str, ...] | None, limit: int
    ) -> Sequence[TaskLogEntry]:
        return await self._list(TaskLogEntry.celery_task_id == celery_task_id, after, levels, limit)

    async def list_for_document(
        self, document_id: uuid.UUID, *, after: int, levels: tuple[str, ...] | None, limit: int
    ) -> Sequence[TaskLogEntry]:
        return await self._list(TaskLogEntry.document_id == document_id, after, levels, limit)

    async def purge(self, before: datetime) -> int:
        result = await self.db.execute(delete(TaskLogEntry).where(TaskLogEntry.ts < before))
        return result.rowcount or 0

    async def _list(
        self, where: ColumnElement[bool], after: int, levels: tuple[str, ...] | None, limit: int
    ) -> Sequence[TaskLogEntry]:
        query = select(TaskLogEntry).where(where, TaskLogEntry.id > after)
        if levels is not None:
            query = query.where(TaskLogEntry.level.in_(levels))
        result = await self.db.execute(query.order_by(TaskLogEntry.id).limit(limit))
        return result.scalars().all()
