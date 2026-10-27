from datetime import datetime

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EnergySettings
from app.models.execution_metric import ExecutionMetric
from app.models.token_usage import UserProfile

_BYTES_PER_GB = 1e9
_SECONDS_PER_HOUR = 3600

# A node has no memory of its own and shares its task's process: counting it as a task would count the
# same time and CPU twice.
TASK = "task"


def _sums(energy: EnergySettings):
    """CPU time at the power a core draws, and the memory held for as long as the task ran at the power
    memory draws, in Wh, with the data centre's overhead on top."""
    joules = (
        ExecutionMetric.cpu_seconds * energy.ENERGY_WATTS_PER_CORE
        + (func.coalesce(ExecutionMetric.peak_rss_bytes, 0) / _BYTES_PER_GB)
        * ExecutionMetric.duration_seconds
        * energy.ENERGY_WATTS_PER_GB
    )
    return (
        func.count(ExecutionMetric.id).label("count"),
        func.coalesce(func.sum(ExecutionMetric.duration_seconds), 0.0).label("duration_seconds"),
        func.coalesce(func.sum(ExecutionMetric.cpu_seconds), 0.0).label("cpu_seconds"),
        func.coalesce(func.max(ExecutionMetric.peak_rss_bytes), 0).label("peak_rss_bytes"),
        (func.coalesce(func.sum(joules), 0.0) / _SECONDS_PER_HOUR * energy.ENERGY_PUE).label("energy_wh"),
    )


class ExecutionMetricRepository:
    def __init__(self, db: AsyncSession, energy: EnergySettings | None = None) -> None:
        self.db = db
        self.energy = energy or EnergySettings()

    async def add(self, metric: ExecutionMetric) -> None:
        self.db.add(metric)

    def _filtered(self, statement, since: datetime, user_id: str | None, *, tasks_only: bool):
        statement = statement.where(ExecutionMetric.created_at >= since)
        if tasks_only:
            statement = statement.where(ExecutionMetric.kind == TASK)
        return statement.where(ExecutionMetric.user_id == user_id) if user_id is not None else statement

    async def totals(self, since: datetime, user_id: str | None):
        statement = select(*_sums(self.energy))
        return (await self.db.execute(self._filtered(statement, since, user_id, tasks_only=True))).one()

    async def by_step(self, since: datetime, user_id: str | None):
        statement = (
            select(ExecutionMetric.kind, ExecutionMetric.step, *_sums(self.energy))
            .group_by(ExecutionMetric.kind, ExecutionMetric.step)
            .order_by(func.sum(ExecutionMetric.duration_seconds).desc())
        )
        return (await self.db.execute(self._filtered(statement, since, user_id, tasks_only=False))).all()

    async def by_day(self, since: datetime, user_id: str | None):
        day = cast(ExecutionMetric.created_at, Date).label("day")
        statement = select(day, *_sums(self.energy)).group_by(day).order_by(day)
        return (await self.db.execute(self._filtered(statement, since, user_id, tasks_only=True))).all()

    async def by_user(self, since: datetime):
        statement = (
            select(ExecutionMetric.user_id, UserProfile.display, UserProfile.email, *_sums(self.energy))
            .outerjoin(UserProfile, UserProfile.user_id == ExecutionMetric.user_id)
            .where(ExecutionMetric.created_at >= since, ExecutionMetric.kind == TASK)
            .group_by(ExecutionMetric.user_id, UserProfile.display, UserProfile.email)
            .order_by(func.sum(ExecutionMetric.duration_seconds).desc())
        )
        return (await self.db.execute(statement)).all()
