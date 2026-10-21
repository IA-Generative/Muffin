import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_refresh_schedule import DocumentRefreshSchedule, RefreshKind
from app.schemas.document import RefreshSchedule


class DocumentRefreshRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, document_id: uuid.UUID) -> DocumentRefreshSchedule | None:
        result = await self.db.execute(
            select(DocumentRefreshSchedule).where(DocumentRefreshSchedule.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def set(
        self, document_id: uuid.UUID, refresh_schedule: RefreshSchedule, next_run_at: datetime
    ) -> DocumentRefreshSchedule:
        schedule = await self.get(document_id)
        if schedule is None:
            schedule = DocumentRefreshSchedule(document_id=document_id)
            self.db.add(schedule)
        schedule.kind = RefreshKind(refresh_schedule.kind)
        schedule.interval_minutes = refresh_schedule.interval_minutes
        schedule.time_of_day = refresh_schedule.time_of_day
        schedule.weekdays = refresh_schedule.weekdays
        schedule.timezone = refresh_schedule.timezone
        schedule.next_run_at = next_run_at
        await self.db.flush()
        return schedule

    async def delete(self, schedule: DocumentRefreshSchedule) -> None:
        await self.db.delete(schedule)
        await self.db.flush()

    async def claim_due(self, now: datetime, limit: int) -> Sequence[DocumentRefreshSchedule]:
        """The schedules due, locked: the caller moves each one forward (or removes it) in the same
        transaction. `SKIP LOCKED` lets two scans running at the same time (one per worker replica)
        each take different rows instead of both refreshing the same document. A document being
        processed is left for a later scan - and not claimed, so it is not delayed by a whole run."""
        result = await self.db.execute(
            select(DocumentRefreshSchedule)
            .join(Document, Document.id == DocumentRefreshSchedule.document_id)
            .where(
                DocumentRefreshSchedule.next_run_at <= now,
                Document.status.not_in([DocumentStatus.PENDING, DocumentStatus.INDEXING]),
            )
            .order_by(DocumentRefreshSchedule.next_run_at)
            .limit(limit)
            .with_for_update(of=DocumentRefreshSchedule, skip_locked=True)
        )
        return result.scalars().all()
