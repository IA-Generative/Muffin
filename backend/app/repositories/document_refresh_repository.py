import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_refresh_schedule import DocumentRefreshSchedule


class DocumentRefreshRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, document_id: uuid.UUID) -> DocumentRefreshSchedule | None:
        result = await self.db.execute(
            select(DocumentRefreshSchedule).where(DocumentRefreshSchedule.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def set(
        self, document_id: uuid.UUID, interval_minutes: int, next_run_at: datetime
    ) -> DocumentRefreshSchedule:
        schedule = await self.get(document_id)
        if schedule is None:
            schedule = DocumentRefreshSchedule(document_id=document_id)
            self.db.add(schedule)
        schedule.interval_minutes = interval_minutes
        schedule.next_run_at = next_run_at
        await self.db.flush()
        return schedule

    async def delete(self, schedule: DocumentRefreshSchedule) -> None:
        await self.db.delete(schedule)
        await self.db.flush()

    async def claim_due(self, now: datetime, limit: int) -> Sequence[uuid.UUID]:
        """The documents due for a refresh, each claimed once: its next_run_at moves forward by its
        interval in the same transaction. `SKIP LOCKED` lets two scans running at the same time (one
        per worker replica) each take different rows instead of both refreshing the same document.
        A document being processed is left for a later scan - and not claimed, so it is not delayed
        by a whole interval."""
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
        schedules = result.scalars().all()
        for schedule in schedules:
            schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
        await self.db.flush()
        return [schedule.document_id for schedule in schedules]
