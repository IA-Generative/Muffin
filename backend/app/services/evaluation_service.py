import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import RUN_EVALUATION_TASK, enqueue_run_evaluation
from app.repositories.collection_repository import CollectionRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.evaluation import EvaluationResultOut, EvaluationRunOut
from app.services import evaluation_artifacts


class CollectionNotFoundError(Exception):
    pass


class EvaluationRunNotFoundError(Exception):
    pass


class EvaluationArtifactNotFoundError(Exception):
    """The run exists but has no artifact (it predates the promptfoo migration, or the
    upload never happened) - its report/results can't be served."""


class EvaluationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.evaluations = EvaluationRepository(db)
        self.tasks = TaskRepository(db)

    async def trigger(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        k: int,
        validated_only: bool = False,
    ) -> str:
        await self._get_accessible(collection_id, user)
        # No EvaluationRun row is created here - see EvaluationRepository.create_run's docstring,
        # the worker posts a fully computed one back once it's done. The Task row (progress/logs
        # tracking, unrelated to the EvaluationRun itself) is created here directly though - same
        # pattern as DocumentUploadService.create_file_document: this request already knows the
        # user, so there's no need for the worker to call back just to record who owns it (it's a
        # single task with no children besides, unlike the document pipeline's cascade).
        celery_task_id = enqueue_run_evaluation(str(collection_id), k, validated_only)
        await self.tasks.create(
            celery_task_id,
            RUN_EVALUATION_TASK,
            user.user_id,
            collection_id=collection_id,
        )
        await self.db.commit()
        return celery_task_id

    async def delete_run(self, collection_id: uuid.UUID, run_id: uuid.UUID, user: RequestContext) -> None:
        await self._get_accessible(collection_id, user)
        run = await self._get_run(collection_id, run_id)
        artifact_keys = [key for key in (run.results_json_key, run.report_html_key) if key]
        await self.evaluations.delete_run(run)
        await self.db.commit()
        # Best-effort, after the rows are gone: a RustFS failure here must not roll
        # the delete back - it would just leave orphaned objects (see storage.delete_objects).
        storage.delete_objects(artifact_keys)

    async def list_runs(self, collection_id: uuid.UUID, user: RequestContext) -> list[EvaluationRunOut]:
        await self._get_accessible(collection_id, user)
        runs = await self.evaluations.list_by_collection(collection_id)
        return [await self._to_out(run) for run in runs]

    async def run_results(
        self, collection_id: uuid.UUID, run_id: uuid.UUID, user: RequestContext
    ) -> list[EvaluationResultOut]:
        """The per-pair detail of one run, normalized from its results.json artifact -
        empty for a run with no artifact (the runs predating the promptfoo migration)."""
        await self._get_accessible(collection_id, user)
        run = await self._get_run(collection_id, run_id)
        tests = evaluation_artifacts.load_tests(run)
        return [evaluation_artifacts.to_result_out(test) for test in tests] if tests else []

    async def run_report(self, collection_id: uuid.UUID, run_id: uuid.UUID, user: RequestContext) -> bytes:
        """The run's promptfoo HTML report - served through the backend so every access
        is re-checked against the user's collection access (never a presigned URL)."""
        await self._get_accessible(collection_id, user)
        run = await self._get_run(collection_id, run_id)
        if not run.report_html_key:
            raise EvaluationArtifactNotFoundError(str(run_id))
        report, _ = storage.get_object(run.report_html_key)
        return report

    async def run_results_json(self, collection_id: uuid.UUID, run_id: uuid.UUID, user: RequestContext) -> bytes:
        """The run's raw promptfoo results.json - the downloadable source of truth."""
        await self._get_accessible(collection_id, user)
        run = await self._get_run(collection_id, run_id)
        if not run.results_json_key:
            raise EvaluationArtifactNotFoundError(str(run_id))
        data, _ = storage.get_object(run.results_json_key)
        return data

    async def _get_run(self, collection_id: uuid.UUID, run_id: uuid.UUID):  # noqa: ANN202
        run = await self.evaluations.get(run_id)
        if run is None or run.collection_id != collection_id:
            raise EvaluationRunNotFoundError(str(run_id))
        return run

    async def _get_accessible(self, collection_id: uuid.UUID, user: RequestContext):  # noqa: ANN202
        collection = await self.collections.get_accessible(collection_id, user.user_id, user.groups)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        return collection

    async def _to_out(self, run) -> EvaluationRunOut:  # noqa: ANN001
        tests = evaluation_artifacts.load_tests(run)
        metrics, golden_metrics = evaluation_artifacts.metrics_from_tests(tests) if tests else (None, None)
        return EvaluationRunOut(
            id=run.id,
            collection_id=run.collection_id,
            created_at=run.created_at,
            k=run.k,
            pair_count=run.pair_count,
            llm_model=run.llm_model,
            snapshot_chunking_strategy=run.snapshot_chunking_strategy,
            snapshot_chunk_size=run.snapshot_chunk_size,
            snapshot_chunk_overlap=run.snapshot_chunk_overlap,
            snapshot_embedding_model=run.snapshot_embedding_model,
            golden_pair_count=run.golden_pair_count,
            validated_pair_count=run.validated_pair_count,
            unvalidated_pair_count=run.unvalidated_pair_count,
            content_hash=run.content_hash,
            metrics=metrics,
            golden_metrics=golden_metrics,
            has_artifacts=bool(run.results_json_key and run.report_html_key),
        )
