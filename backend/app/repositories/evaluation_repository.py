import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationRun


class EvaluationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(self, collection_id: uuid.UUID, data: dict) -> EvaluationRun:
        """One shot: the model has no in-progress state (no status column, see
        app/models/evaluation.py) - a run only ever exists once fully computed, so there's
        nothing to create-then-update. worker/evaluation runs promptfoo, posts the run's
        metadata here, then uploads its artifacts right after (attach_artifacts)."""
        run = EvaluationRun(collection_id=collection_id, **data)
        self.db.add(run)
        await self.db.flush()
        return run

    async def attach_artifacts(self, run: EvaluationRun, results_json_key: str, report_html_key: str) -> None:
        """Records where the run's promptfoo artifacts live in RustFS - the second half
        of a run's creation, once the worker has uploaded both files."""
        run.results_json_key = results_json_key
        run.report_html_key = report_html_key
        await self.db.flush()

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[EvaluationRun]:
        result = await self.db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.collection_id == collection_id)
            .order_by(EvaluationRun.created_at.desc())
        )
        return result.scalars().all()

    async def get(self, run_id: uuid.UUID) -> EvaluationRun | None:
        result = await self.db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
        return result.scalar_one_or_none()

    async def find_existing(self, collection_id: uuid.UUID, content_hash: str, llm_model: str) -> uuid.UUID | None:
        """Returns the id of an already-persisted run for this exact (collection, content, model)
        triple, or None - so the worker can skip re-evaluating a collection when nothing that
        affects the result has changed since the last run with the same parameters (same dedup
        strategy as DiscussionScoreRepository.find_existing)."""
        result = await self.db.execute(
            select(EvaluationRun.id).where(
                EvaluationRun.collection_id == collection_id,
                EvaluationRun.content_hash == content_hash,
                EvaluationRun.llm_model == llm_model,
            )
        )
        return result.scalar_one_or_none()

    async def delete_run(self, run: EvaluationRun) -> None:
        await self.db.delete(run)
        await self.db.flush()
