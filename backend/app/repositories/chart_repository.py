import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chart import Chart


class ChartRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, chart: Chart) -> Chart:
        self.db.add(chart)
        await self.db.flush()
        return chart

    async def count_for_run(self, run_id: uuid.UUID) -> int:
        result = await self.db.execute(select(func.count()).select_from(Chart).where(Chart.run_id == run_id))
        return result.scalar_one()

    async def get_in_conversation(self, chart_id: uuid.UUID, conversation_id: uuid.UUID) -> Chart | None:
        result = await self.db.execute(
            select(Chart).where(Chart.id == chart_id, Chart.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def attach_run_to_message(self, run_id: uuid.UUID, message_id: uuid.UUID) -> None:
        """The charts of a run belong to the message that was made from its answer."""
        await self.db.execute(update(Chart).where(Chart.run_id == run_id).values(message_id=message_id))

    async def keys_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[str]:
        result = await self.db.execute(select(Chart.s3_key).where(Chart.conversation_id == conversation_id))
        return result.scalars().all()
