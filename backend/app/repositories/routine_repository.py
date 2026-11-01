import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.routine import Routine, RoutineRun, RoutineRunStatus, RoutineSettings, RoutineState
from app.models.token_usage import TokenUsage, UserProfile


class RoutineRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- the limits ---

    async def settings(self) -> RoutineSettings:
        settings = await self.db.get(RoutineSettings, 1)
        if settings is None:
            settings = RoutineSettings(id=1)
            self.db.add(settings)
            await self.db.flush()
            await self.db.refresh(settings)
        return settings

    # --- routines ---

    async def add(self, routine: Routine) -> Routine:
        self.db.add(routine)
        await self.db.flush()
        await self.db.refresh(routine)
        return routine

    async def get(self, routine_id: uuid.UUID) -> Routine | None:
        return await self.db.get(Routine, routine_id)

    async def get_owned(self, routine_id: uuid.UUID, owner_id: str) -> Routine | None:
        result = await self.db.execute(select(Routine).where(Routine.id == routine_id, Routine.owner_id == owner_id))
        return result.scalar_one_or_none()

    async def get_locked(self, routine_id: uuid.UUID) -> Routine | None:
        """The routine, its row locked until the end of the transaction: a run is started by one caller at a time."""
        result = await self.db.execute(
            select(Routine).where(Routine.id == routine_id).with_for_update().execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_owned(self, owner_id: str) -> Sequence[Routine]:
        result = await self.db.execute(
            select(Routine).where(Routine.owner_id == owner_id).order_by(Routine.created_at.desc())
        )
        return result.scalars().all()

    async def list_all(self, limit: int, offset: int) -> tuple[Sequence[Routine], int]:
        total = await self.db.scalar(select(func.count()).select_from(Routine)) or 0
        result = await self.db.execute(select(Routine).order_by(Routine.created_at.desc()).limit(limit).offset(offset))
        return result.scalars().all(), total

    async def count_active(self, owner_id: str, excluding: uuid.UUID | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(Routine)
            .where(Routine.owner_id == owner_id, Routine.state == RoutineState.ACTIVE)
        )
        if excluding is not None:
            statement = statement.where(Routine.id != excluding)
        return await self.db.scalar(statement) or 0

    async def delete(self, routine: Routine) -> None:
        await self.db.delete(routine)
        await self.db.flush()

    async def claim_due(self, now: datetime, limit: int) -> Sequence[Routine]:
        """The active routines that are due, locked: the caller moves each one's next date forward in the same
        transaction. `SKIP LOCKED` lets two replicas sweeping at the same time take different rows, so that a date is
        run once."""
        result = await self.db.execute(
            select(Routine)
            .where(Routine.state == RoutineState.ACTIVE, Routine.next_run_at.is_not(None), Routine.next_run_at <= now)
            .order_by(Routine.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()

    async def inactive_active(self, seen_before: datetime) -> Sequence[Routine]:
        """Active routines whose owner has not opened the application since `seen_before` - or, never seen, since the
        routine was made."""
        result = await self.db.execute(
            select(Routine)
            .outerjoin(UserProfile, UserProfile.user_id == Routine.owner_id)
            .where(
                Routine.state == RoutineState.ACTIVE,
                func.coalesce(UserProfile.last_seen_at, Routine.created_at) < seen_before,
            )
        )
        return result.scalars().all()

    async def profile(self, user_id: str) -> UserProfile | None:
        return await self.db.get(UserProfile, user_id)

    # --- the runs ---

    async def add_run(self, run: RoutineRun) -> RoutineRun:
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, routine_run_id: uuid.UUID) -> RoutineRun | None:
        return await self.db.get(RoutineRun, routine_run_id)

    async def list_runs(self, routine_id: uuid.UUID, limit: int, offset: int) -> tuple[Sequence[RoutineRun], int]:
        total = (
            await self.db.scalar(
                select(func.count()).select_from(RoutineRun).where(RoutineRun.routine_id == routine_id)
            )
            or 0
        )
        result = await self.db.execute(
            select(RoutineRun)
            .where(RoutineRun.routine_id == routine_id)
            .order_by(RoutineRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def last_runs(self, routine_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, RoutineRun]:
        if not routine_ids:
            return {}
        result = await self.db.execute(
            select(RoutineRun)
            .where(RoutineRun.routine_id.in_(routine_ids))
            .distinct(RoutineRun.routine_id)
            .order_by(RoutineRun.routine_id, RoutineRun.started_at.desc())
        )
        return {run.routine_id: run for run in result.scalars()}

    async def is_running(self, routine_id: uuid.UUID) -> bool:
        return bool(
            await self.db.scalar(
                select(func.count())
                .select_from(RoutineRun)
                .where(RoutineRun.routine_id == routine_id, RoutineRun.status == RoutineRunStatus.RUNNING)
            )
        )

    async def count_running(self) -> int:
        return (
            await self.db.scalar(
                select(func.count()).select_from(RoutineRun).where(RoutineRun.status == RoutineRunStatus.RUNNING)
            )
            or 0
        )

    async def count_runs_since(self, owner_id: str, since: datetime) -> int:
        """What a person's routines asked of the agent since `since`: a run that was skipped asked nothing."""
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(RoutineRun)
                .join(Routine, Routine.id == RoutineRun.routine_id)
                .where(
                    Routine.owner_id == owner_id,
                    RoutineRun.started_at >= since,
                    RoutineRun.status != RoutineRunStatus.SKIPPED,
                )
            )
            or 0
        )

    async def stale_runs(self, started_before: datetime) -> Sequence[RoutineRun]:
        result = await self.db.execute(
            select(RoutineRun).where(
                RoutineRun.status == RoutineRunStatus.RUNNING, RoutineRun.started_at < started_before
            )
        )
        return result.scalars().all()

    async def usage(self, since: datetime, user_id: str | None) -> dict[str, int]:
        """What the routines cost in the period, apart from the rest of the consumption: the runs that asked the agent
        (a skipped date asked nothing) and their tokens. One person's, or everyone's."""
        statement = (
            select(func.count(), func.coalesce(func.sum(RoutineRun.total_tokens), 0))
            .select_from(RoutineRun)
            .join(Routine, Routine.id == RoutineRun.routine_id)
            .where(RoutineRun.started_at >= since, RoutineRun.status != RoutineRunStatus.SKIPPED)
        )
        if user_id is not None:
            statement = statement.where(Routine.owner_id == user_id)
        runs, tokens = (await self.db.execute(statement)).one()
        return {"runs": int(runs), "total_tokens": int(tokens)}

    async def tokens_by_routine(self, routine_ids: Sequence[uuid.UUID], since: datetime) -> dict[uuid.UUID, int]:
        if not routine_ids:
            return {}
        result = await self.db.execute(
            select(RoutineRun.routine_id, func.coalesce(func.sum(RoutineRun.total_tokens), 0))
            .where(RoutineRun.routine_id.in_(routine_ids), RoutineRun.started_at >= since)
            .group_by(RoutineRun.routine_id)
        )
        return {routine_id: int(total) for routine_id, total in result}

    async def tokens_of(self, run_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(TokenUsage.run_id == run_id)
            )
            or 0
        )

    # --- what is new ---

    async def documents_changed_since(self, collection_ids: Sequence[uuid.UUID], since: datetime) -> int:
        """Documents of these collections added or changed since `since`, and ready to be searched."""
        if not collection_ids:
            return 0
        return (
            await self.db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.collection_id.in_(collection_ids),
                    Document.status == DocumentStatus.INDEXED,
                    Document.updated_at > since,
                )
            )
            or 0
        )
