import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import RUN_EVALUATION_TASK, enqueue_run_evaluation
from app.repositories.collection_repository import CollectionRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.evaluation import EvaluationResultOut, EvaluationRunOut


class CollectionNotFoundError(Exception):
    pass


class EvaluationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.evaluations = EvaluationRepository(db)
        self.tasks = TaskRepository(db)

    async def trigger(self, collection_id: uuid.UUID, user: RequestContext, k: int) -> str:
        await self._get_accessible(collection_id, user)
        # No EvaluationRun row is created here - see EvaluationRepository.create_run's docstring,
        # the worker posts a fully computed one back once it's done. The Task row (progress/logs
        # tracking, unrelated to the EvaluationRun itself) is created here directly though - same
        # pattern as DocumentUploadService.create_file_document: this request already knows the
        # user, so there's no need for the worker to call back just to record who owns it (it's a
        # single task with no children besides, unlike the document pipeline's cascade).
        celery_task_id = enqueue_run_evaluation(str(collection_id), k)
        await self.tasks.create(celery_task_id, RUN_EVALUATION_TASK, user.user_id, collection_id=collection_id)
        await self.db.commit()
        return celery_task_id

    async def list_runs(self, collection_id: uuid.UUID, user: RequestContext) -> list[EvaluationRunOut]:
        await self._get_accessible(collection_id, user)
        runs = await self.evaluations.list_by_collection(collection_id)
        return [self._to_out(run) for run in runs]

    async def _get_accessible(self, collection_id: uuid.UUID, user: RequestContext):  # noqa: ANN202
        collection = await self.collections.get_accessible(collection_id, user.user_id, user.groups)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        return collection

    def _to_out(self, run) -> EvaluationRunOut:  # noqa: ANN001
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
            precision_at_k=run.precision_at_k,
            recall_at_k=run.recall_at_k,
            mrr=run.mrr,
            ndcg=run.ndcg,
            results=[
                EvaluationResultOut(
                    id=result.id,
                    qa_pair_id=result.qa_pair_id,
                    question=result.question,
                    expected_answer=result.expected_answer,
                    generated_answer=result.generated_answer,
                    precision_at_k=result.precision_at_k,
                    recall_at_k=result.recall_at_k,
                    reciprocal_rank=result.reciprocal_rank,
                    ndcg=result.ndcg,
                    retrieved_sources=[source.source for source in result.retrieved_sources],
                )
                for result in run.results
            ],
        )
