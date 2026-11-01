from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EnergySettings
from app.core.security.factory import RequestContext
from app.models.execution_metric import ExecutionMetric
from app.models.token_usage import TokenUsage, TokenUsageKind
from app.repositories.execution_metric_repository import ExecutionMetricRepository
from app.repositories.token_usage_repository import TokenUsageRepository
from app.schemas.internal_pipeline import ExecutionMetricIn, LlmUsageContext
from app.schemas.usage import (
    DayUsage,
    EnergyAssumptions,
    ExecutionDay,
    ExecutionOut,
    ExecutionStep,
    ExecutionSums,
    ExecutionUser,
    ModelUsage,
    StepUsage,
    UsageOut,
    UsageSums,
    UserUsage,
)


class NotAdminError(Exception):
    pass


def _sums(row) -> dict:  # noqa: ANN001
    return {
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "images": row.images,
        "pixels": row.pixels,
        "calls": row.calls,
    }


def _execution_sums(row) -> dict:  # noqa: ANN001
    return {
        "count": row.count,
        "duration_seconds": row.duration_seconds,
        "cpu_seconds": row.cpu_seconds,
        "peak_rss_bytes": row.peak_rss_bytes,
        "energy_wh": row.energy_wh,
    }


def _display(user: RequestContext) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email or user.user_id


class UsageService:
    """Tokens consumed by every LLM call made through the internal proxy, per step, day, model
    and person."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.usage = TokenUsageRepository(db)
        self.energy = EnergySettings()
        self.executions = ExecutionMetricRepository(db, self.energy)

    async def record(
        self,
        context: LlmUsageContext | None,
        kind: TokenUsageKind,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        *,
        images: int = 0,
        pixels: int = 0,
    ) -> None:
        """Best-effort: an LLM call already succeeded by the time this runs, so a failure here is
        logged and swallowed rather than failing the worker's call."""
        context = context or LlmUsageContext()
        try:
            input_tokens, output_tokens = input_tokens or 0, output_tokens or 0
            await self.usage.add(
                TokenUsage(
                    user_id=await self._resolve_user(context),
                    step=context.step or "unknown",
                    kind=kind,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    images=images,
                    pixels=pixels,
                    run_id=context.run_id,
                    document_id=context.document_id,
                    collection_id=context.collection_id,
                )
            )
            await self.db.commit()
        except Exception:
            logger.exception("Failed to record LLM token usage")
            await self.db.rollback()

    async def record_execution(self, metric: ExecutionMetricIn) -> None:
        """Best-effort, like record: a worker task that already ran must not fail because its cost
        could not be written down."""
        try:
            context = LlmUsageContext(
                user_id=metric.user_id,
                run_id=metric.run_id,
                document_id=metric.document_id,
                collection_id=metric.collection_id,
            )
            await self.executions.add(
                ExecutionMetric(
                    user_id=await self._resolve_user(context),
                    kind=metric.kind,
                    step=metric.step,
                    duration_seconds=metric.duration_seconds,
                    cpu_seconds=metric.cpu_seconds,
                    peak_rss_bytes=metric.peak_rss_bytes,
                    run_id=metric.run_id,
                    document_id=metric.document_id,
                    collection_id=metric.collection_id,
                )
            )
            await self.db.commit()
        except Exception:
            logger.exception("Failed to record an execution metric")
            await self.db.rollback()

    async def _resolve_user(self, context: LlmUsageContext) -> str | None:
        """The user the call was made for: given as is, or the run's author, the person who added
        the document, the collection's owner - the most specific the worker could tell."""
        if context.user_id:
            return context.user_id
        if context.run_id:
            return await self.usage.run_user(context.run_id)
        if context.document_id:
            return await self.usage.document_user(context.document_id)
        if context.collection_id:
            return await self.usage.collection_user(context.collection_id)
        return None

    async def save_profile(self, user: RequestContext) -> None:
        """Best-effort, same reasoning as record: who is logged in must never fail because of it."""
        try:
            await self.usage.save_profile(user.user_id, _display(user), user.email or None)
            await self.db.commit()
        except Exception:
            logger.exception("Failed to save the user profile")
            await self.db.rollback()

    async def mine(self, user: RequestContext, days: int) -> UsageOut:
        return await self._report(days, user.user_id, with_users=False)

    async def overall(self, user: RequestContext, days: int, user_id: str | None = None) -> UsageOut:
        """Everyone's consumption, or only `user_id`'s - by_user always lists everyone, so the
        admin can switch from one person to another."""
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        return await self._report(days, user_id, with_users=True)

    async def _report(self, days: int, user_id: str | None, with_users: bool) -> UsageOut:
        since = datetime.now(UTC) - timedelta(days=days)
        return UsageOut(
            days=days,
            totals=UsageSums(**_sums(await self.usage.totals(since, user_id))),
            by_step=[StepUsage(step=row.step, **_sums(row)) for row in await self.usage.by_step(since, user_id)],
            by_day=[DayUsage(day=row.day, **_sums(row)) for row in await self.usage.by_day(since, user_id)],
            by_model=[ModelUsage(model=row.model, **_sums(row)) for row in await self.usage.by_model(since, user_id)],
            by_user=[
                UserUsage(user_id=row.user_id, display=row.display, **_sums(row))
                for row in await self.usage.by_user(since)
            ]
            if with_users
            else [],
            execution=await self._execution(since, user_id, with_users),
        )

    async def _execution(self, since: datetime, user_id: str | None, with_users: bool) -> ExecutionOut:
        return ExecutionOut(
            totals=ExecutionSums(**_execution_sums(await self.executions.totals(since, user_id))),
            by_step=[
                ExecutionStep(kind=row.kind, step=row.step, **_execution_sums(row))
                for row in await self.executions.by_step(since, user_id)
            ],
            by_day=[
                ExecutionDay(day=row.day, **_execution_sums(row))
                for row in await self.executions.by_day(since, user_id)
            ],
            by_user=[
                ExecutionUser(user_id=row.user_id, display=row.display, **_execution_sums(row))
                for row in await self.executions.by_user(since)
            ]
            if with_users
            else [],
            assumptions=EnergyAssumptions(
                watts_per_core=self.energy.ENERGY_WATTS_PER_CORE,
                watts_per_gb=self.energy.ENERGY_WATTS_PER_GB,
                pue=self.energy.ENERGY_PUE,
            ),
        )
