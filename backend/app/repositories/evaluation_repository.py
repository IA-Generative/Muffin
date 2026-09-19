import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evaluation import EvaluationResult, EvaluationResultSource, EvaluationRun


class EvaluationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(self, collection_id: uuid.UUID, data: dict[str, Any]) -> EvaluationRun:
        """One shot: the model has no in-progress state (no status column, see
        app/models/evaluation.py) - a run only ever exists once fully computed, so there's
        nothing to create-then-update. worker/evaluation computes everything in memory and posts
        it here once at the end."""
        results_in = data.pop("results")
        run = EvaluationRun(collection_id=collection_id, **data)
        self.db.add(run)
        await self.db.flush()

        for result_in in results_in:
            sources = result_in.pop("retrieved_sources", [])
            result = EvaluationResult(run_id=run.id, **result_in)
            self.db.add(result)
            await self.db.flush()
            for source in sources:
                self.db.add(EvaluationResultSource(evaluation_result_id=result.id, source=source))

        await self.db.flush()
        return run

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[EvaluationRun]:
        result = await self.db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.collection_id == collection_id)
            .options(selectinload(EvaluationRun.results).selectinload(EvaluationResult.retrieved_sources))
            .order_by(EvaluationRun.created_at.desc())
        )
        return result.scalars().all()

    async def get(self, run_id: uuid.UUID) -> EvaluationRun | None:
        result = await self.db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.id == run_id)
            .options(selectinload(EvaluationRun.results).selectinload(EvaluationResult.retrieved_sources))
        )
        return result.scalar_one_or_none()
