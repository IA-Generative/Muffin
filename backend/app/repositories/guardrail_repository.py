import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardrail import Guardrail, GuardrailAudit, GuardrailPolicy, GuardrailResult


class GuardrailRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- the policy ---

    async def policy(self) -> GuardrailPolicy:
        policy = await self.db.get(GuardrailPolicy, 1)
        if policy is None:
            policy = GuardrailPolicy(id=1)
            self.db.add(policy)
            await self.db.flush()
            await self.db.refresh(policy)
        return policy

    # --- the guardrails ---

    async def get(self, guardrail_id: uuid.UUID) -> Guardrail | None:
        return await self.db.get(Guardrail, guardrail_id)

    async def get_by_name(self, name: str) -> Guardrail | None:
        result = await self.db.execute(select(Guardrail).where(Guardrail.name == name))
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Guardrail]:
        result = await self.db.execute(select(Guardrail).order_by(Guardrail.stage, Guardrail.position, Guardrail.name))
        return result.scalars().all()

    async def list_enabled(self) -> Sequence[Guardrail]:
        result = await self.db.execute(
            select(Guardrail)
            .where(Guardrail.enabled.is_(True))
            .order_by(Guardrail.stage, Guardrail.position, Guardrail.name)
        )
        return result.scalars().all()

    async def count(self) -> int:
        return await self.db.scalar(select(func.count()).select_from(Guardrail)) or 0

    async def next_position(self) -> int:
        return (await self.db.scalar(select(func.coalesce(func.max(Guardrail.position), 0)))) + 1

    async def add(self, guardrail: Guardrail) -> Guardrail:
        self.db.add(guardrail)
        await self.db.flush()
        await self.db.refresh(guardrail)
        return guardrail

    async def delete(self, guardrail: Guardrail) -> None:
        await self.db.delete(guardrail)
        await self.db.flush()

    # --- what they said ---

    async def has_results(self, run_id: uuid.UUID) -> bool:
        return bool(
            await self.db.scalar(
                select(func.count()).select_from(GuardrailResult).where(GuardrailResult.run_id == run_id)
            )
        )

    async def add_results(self, results: Sequence[GuardrailResult]) -> None:
        self.db.add_all(results)
        await self.db.flush()

    async def purge_results(self, before: datetime) -> int:
        return (await self.db.execute(delete(GuardrailResult).where(GuardrailResult.created_at < before))).rowcount

    async def stats(self, since: datetime) -> Sequence:
        """By guardrail and by day: how many verdicts, how many flagged, how many requests it actually stopped, and the
        time it took - counts and times only, never any text."""
        day = func.date_trunc("day", GuardrailResult.created_at)
        return (
            await self.db.execute(
                select(
                    GuardrailResult.guardrail_id,
                    GuardrailResult.guardrail_name,
                    day.label("day"),
                    func.count().label("evaluated"),
                    func.count().filter(GuardrailResult.verdict == "flagged").label("flagged"),
                    func.count().filter(GuardrailResult.action == "blocked").label("blocked"),
                    func.count().filter(GuardrailResult.verdict.in_(("error", "timeout"))).label("failed"),
                    func.coalesce(func.avg(GuardrailResult.latency_ms), 0).label("avg_latency_ms"),
                    func.coalesce(func.max(GuardrailResult.latency_ms), 0).label("max_latency_ms"),
                )
                .where(GuardrailResult.created_at >= since, GuardrailResult.verdict != "cancelled")
                .group_by(GuardrailResult.guardrail_id, GuardrailResult.guardrail_name, day)
                .order_by(day.desc(), GuardrailResult.guardrail_name)
            )
        ).all()

    async def totals(self, since: datetime) -> tuple[int, int]:
        """The requests that went through at least one guardrail, and the ones that were stopped."""
        row = (
            await self.db.execute(
                select(
                    func.count(func.distinct(GuardrailResult.run_id)),
                    func.count(func.distinct(case((GuardrailResult.action == "blocked", GuardrailResult.run_id)))),
                ).where(GuardrailResult.created_at >= since)
            )
        ).one()
        return int(row[0]), int(row[1])

    # --- who changed what ---

    async def add_audit(self, entry: GuardrailAudit) -> None:
        self.db.add(entry)
        await self.db.flush()

    async def audit(
        self, limit: int, offset: int, guardrail_id: uuid.UUID | None
    ) -> tuple[Sequence[GuardrailAudit], int]:
        statement = select(GuardrailAudit)
        count = select(func.count()).select_from(GuardrailAudit)
        if guardrail_id is not None:
            statement = statement.where(GuardrailAudit.guardrail_id == guardrail_id)
            count = count.where(GuardrailAudit.guardrail_id == guardrail_id)
        rows = await self.db.execute(statement.order_by(GuardrailAudit.created_at.desc()).limit(limit).offset(offset))
        return rows.scalars().all(), await self.db.scalar(count) or 0
