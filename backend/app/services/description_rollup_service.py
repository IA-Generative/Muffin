import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import redis_connector
from app.core.tasks import ROLLUP_COLLECTION_DESCRIPTION_TASK, enqueue_rollup_collection_description
from app.repositories.collection_repository import CollectionRepository
from app.repositories.task_repository import TaskRepository

# A parent's description is recomputed at most once per window (#218): the first change below it
# schedules the run this many seconds later, every other change within the window is absorbed by
# that same run, which reads the latest state when it actually executes.
ROLLUP_DELAY_SECONDS = 60
_LOCK_PREFIX = "collection-description-rollup:"

# Module attribute (not closed over) so tests can swap in fakeredis with monkeypatch.setattr.
_redis = redis_connector.client


class DescriptionRollupService:
    """Schedules the recomputation of a parent collection's description from its own documents
    and its sub-collections' descriptions (worker/document_process's rollup_collection_description).

    The single place every trigger goes through - a sub-collection's description changing (by the
    pipeline or by hand), a collection moving in or out, a sub-collection being deleted - so the
    grouping window is enforced once. Each recomputation that does change the parent's description
    reports it through the same internal route as any other, which schedules the next level up: the
    propagation stops by itself at the first level whose description doesn't change."""

    def __init__(self, db: AsyncSession) -> None:
        self.collections = CollectionRepository(db)
        self.tasks = TaskRepository(db)

    async def schedule(self, collection_id: uuid.UUID | None) -> None:
        """No-op for None (a root has no parent to update) or when a run is already pending for
        this collection. Never raises: a failure here must not fail the change that triggered it,
        the parent's description just falls behind until the next trigger."""
        if collection_id is None:
            return
        try:
            if not _redis.set(f"{_LOCK_PREFIX}{collection_id}", "1", nx=True, ex=ROLLUP_DELAY_SECONDS):
                return
            collection = await self.collections.get_by_id(collection_id)
            if collection is None:
                return
            celery_task_id = enqueue_rollup_collection_description(str(collection_id), ROLLUP_DELAY_SECONDS)
            await self.tasks.create(
                celery_task_id, ROLLUP_COLLECTION_DESCRIPTION_TASK, collection.owner_id, collection_id=collection_id
            )
        except Exception:
            logger.exception(f"Failed to schedule the description rollup of collection {collection_id}")
