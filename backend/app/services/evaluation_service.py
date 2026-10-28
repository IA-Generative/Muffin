import asyncio
import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import ACTIVE_TASK_STATES, RUN_EVALUATION_TASK, enqueue_run_evaluation, get_task_status
from app.models.collection import CollectionSettings
from app.models.qa import QaPair
from app.repositories.collection_repository import CollectionRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.evaluation import EvaluationResultOut, EvaluationRunOut
from app.services import evaluation_artifacts


class CollectionNotFoundError(Exception):
    pass


# The metrics a run scores (the worker's create_tests.py assertions, by their namedScores
# key) - part of the dedup hash: a run that also scores context faithfulness must not be
# deduped against an older one that scored factuality alone, its artifact would lack the
# new score. This is the ONLY place the backend still names metrics: the display path is
# generic (it serves whatever the artifact holds, see evaluation_artifacts), but the
# trigger-time hash must know what the worker WILL score before any artifact exists -
# and it cannot import worker code. Keep in sync with the worker's list
# (worker/evaluation/app/promptfoo/create_tests.py's SCORED_METRICS).
_SCORED_METRICS = ["context_chunk_count", "context_faithfulness", "factuality"]

# How long after dispatch a run_evaluation task may still be considered queued or running
# (see EvaluationService.is_running) - generous for the longest realistic evaluation, short
# enough that a stale task whose Celery result is gone never reads as "in progress" for ever.
EVALUATION_RUNNING_WINDOW = timedelta(hours=1)


def _evaluation_hash(
    pairs: Sequence[QaPair],
    settings: CollectionSettings,
    k: int,
    llm_model: str,
    generator_model: str,
    validated_only: bool,
) -> str:
    """SHA-256 of everything that affects an evaluation run's result, over the same inputs the
    worker hashes (worker/evaluation/app/tasks.py's _evaluation_hash, which fetches them through
    the internal API): the QA pairs (id, question, answer, document_id, validated, golden,
    relevant documents), the chunking/embedding config, k, the judge model, the generator
    model, the scored metrics and the validated_only scope. MUST stay in sync with the
    worker's copy - the trigger-time dedup check below only works if both produce the same
    digest for the same collection state. Both sides pin the same fixture digest in their
    tests (tests/services/test_evaluation_service.py and worker/evaluation/tests/test_tasks.py)
    so a drift breaks them.
    """
    pairs_fingerprint = [
        {
            "id": str(pair.id),
            "question": pair.question,
            "answer": pair.answer,
            "document_id": str(pair.document_id) if pair.document_id else None,
            "validated": pair.validated,
            "golden": bool(pair.golden),
            "relevant_document_ids": sorted(str(i) for i in (pair.relevant_document_ids or [])),
        }
        for pair in sorted(pairs, key=lambda pair: str(pair.id))
    ]
    payload = {
        "qa_pairs": pairs_fingerprint,
        "chunking_strategy": settings.chunking_strategy,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        # Same resolution as the internal settings endpoint the worker reads.
        "embedding_model": settings.index_embedding_model or settings.embedding_model,
        "k": k,
        "llm_model": llm_model,
        "generator_model": generator_model,
        "scored_metrics": _SCORED_METRICS,
        "validated_only": validated_only,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class EvaluationTriggerResult:
    """What a trigger produced: either a dispatched Celery task (celery_task_id set) or an
    already-persisted identical run the trigger refused to duplicate (skipped_run_id set)."""

    celery_task_id: str | None = None
    skipped_run_id: uuid.UUID | None = None
    skipped_run_created_at: datetime | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_run_id is not None


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
        self.qa_pairs = QaPairRepository(db)
        self.tasks = TaskRepository(db)

    async def trigger(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        k: int,
        validated_only: bool = False,
        default_chat_model: str | None = None,
    ) -> EvaluationTriggerResult:
        collection = await self._get_accessible(collection_id, user)
        # Dedup at trigger time, so the user learns immediately that an identical run already
        # exists instead of watching a task that skips (the worker re-checks on its side - the
        # race window between two rapid triggers is its to catch). Same models the worker's
        # run_evaluation resolves: the judge is the collection's evaluation model falling back
        # to the hub's default chat model, the generator is always that default. Without a
        # default chat model the worker no-ops ("No chat model available"), so no run can exist
        # to dedup against - dispatch as before and let it log.
        if default_chat_model is not None:
            judge_model = (collection.settings.generation_models or {}).get("evaluation") or default_chat_model
            pairs = await self.qa_pairs.list_by_collection(collection_id)
            content_hash = _evaluation_hash(
                pairs, collection.settings, k, judge_model, default_chat_model, validated_only
            )
            existing_id = await self.evaluations.find_existing(collection_id, content_hash, judge_model)
            if existing_id is not None:
                existing = await self.evaluations.get(existing_id)
                return EvaluationTriggerResult(
                    skipped_run_id=existing.id,
                    skipped_run_created_at=existing.created_at,
                )
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
        return EvaluationTriggerResult(celery_task_id=celery_task_id)

    async def is_running(self, collection_id: uuid.UUID, user: RequestContext) -> bool:
        """Whether an evaluation is currently queued or running for the collection - read from
        the most recent run_evaluation Task row's live Celery status, so the UI can show the
        in-progress state after a reload (the frontend's own flag is in-memory only)."""
        await self._get_accessible(collection_id, user)
        task = await self.tasks.latest_by_collection_and_name(collection_id, RUN_EVALUATION_TASK)
        if task is None:
            return False
        # Celery reports PENDING for a task id it no longer knows (its result expired, or the
        # result backend was flushed) - indistinguishable from a task still waiting in the
        # queue. A task older than this window can't still be queued or running, so it's not
        # reported as such: without this, an old run would read as "in progress" for ever.
        if task.created_at < datetime.now(UTC) - EVALUATION_RUNNING_WINDOW:
            return False
        # Redis is called off the event loop, same as TaskService.revoke.
        return await asyncio.to_thread(get_task_status, task.celery_task_id) in ACTIVE_TASK_STATES

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
        metrics, golden_metrics, all_metrics = (
            evaluation_artifacts.metrics_from_tests(tests) if tests else (None, None, None)
        )
        golden_pass_rate, reference_pass_rate, overall_pass_rate = (
            evaluation_artifacts.pass_rates(tests) if tests else (None, None, None)
        )
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
            all_metrics=all_metrics,
            golden_pass_rate=golden_pass_rate,
            reference_pass_rate=reference_pass_rate,
            overall_pass_rate=overall_pass_rate,
            has_artifacts=bool(run.results_json_key and run.report_html_key),
        )
