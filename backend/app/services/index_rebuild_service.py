import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.tasks import REBUILD_INDEX_TASK, enqueue_rebuild_index
from app.models.index_rebuild import ACTIVE_REBUILD_STATUSES, IndexRebuild, IndexRebuildStatus
from app.models.task import TaskStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.index_rebuild_repository import IndexRebuildRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.index_rebuild import IndexRebuildOut, RebuildPlanOut, RebuildPointIn, RebuildPointOut
from app.services import vector_store

from .collection_service import CollectionNotFoundError

# Points handed to the worker per plan: enough to keep its embedding calls busy, few enough that a
# plan stays quick to compute and a crash loses little.
PLAN_LIMIT = 1000


class RebuildInProgressError(Exception):
    """The collection already has a rebuild building, or awaiting validation."""


class RebuildNotFoundError(Exception):
    pass


class RebuildStateError(Exception):
    """The rebuild isn't in a state that allows this (e.g. validating one still building)."""


def _working_model(rebuild: IndexRebuild) -> str:
    return rebuild.previous_model if rebuild.status == IndexRebuildStatus.ROLLED_BACK else rebuild.target_model


class IndexRebuildService:
    """Blue/green rebuild of a collection's search index for a new embedding model (#12).

    The active index (chunks_<id>) keeps answering every search while a second one is built next to
    it from PostgreSQL. The build is a reconciliation, not a cursor: each plan compares what the index
    holds to what PostgreSQL says it should (missing points, texts that changed, vectors made with
    another model, points that no longer exist) - so documents added or removed during the build are
    caught too, and a crashed job just resumes. When nothing is left, both indexes are swapped in one
    atomic alias switch and the new one is reconciled once more, to catch what was written in
    between. The old index is kept until the owner validates the switch, or rolls back to it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.rebuilds = IndexRebuildRepository(db)
        self.tasks = TaskRepository(db)

    # -- the owner's side -------------------------------------------------------------------------

    async def start(self, collection_id: uuid.UUID, user: RequestContext) -> IndexRebuildOut:
        collection = await self.collections.get(collection_id, user.user_id)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        if await self.rebuilds.get_active(collection_id) is not None:
            raise RebuildInProgressError(str(collection_id))
        settings = collection.settings
        # A second index left over by a rebuild that failed: it is rebuilt from scratch.
        vector_store.delete_next_index(collection_id)
        rebuild = IndexRebuild(
            collection_id=collection_id,
            status=IndexRebuildStatus.BUILDING,
            target_model=settings.embedding_model,
            previous_model=settings.index_embedding_model or settings.embedding_model,
            total_points=0,
            done_points=0,
            requested_by=user.user_id,
        )
        try:
            await self.rebuilds.add(rebuild)
            await self.db.commit()
        except IntegrityError as error:  # the lock, raced by a second request
            await self.db.rollback()
            raise RebuildInProgressError(str(collection_id)) from error
        task_id = str(uuid.uuid4())
        await self.tasks.create(task_id, REBUILD_INDEX_TASK, user.user_id, collection_id=collection_id)
        await self.db.commit()
        try:
            result_id = enqueue_rebuild_index(str(rebuild.id), task_id=task_id)
        except Exception as exc:
            await self.tasks.set_status(task_id, TaskStatus.FAILURE, str(exc))
            await self.db.commit()
            raise
        await self.tasks.rename_celery_task_id(task_id, result_id)
        await self.db.commit()
        return IndexRebuildOut.model_validate(rebuild)

    async def latest(self, collection_id: uuid.UUID, user: RequestContext) -> IndexRebuildOut | None:
        if await self.collections.get_accessible(collection_id, user.user_id, user.groups) is None:
            raise CollectionNotFoundError(str(collection_id))
        rebuild = await self.rebuilds.get_latest(collection_id)
        return IndexRebuildOut.model_validate(rebuild) if rebuild else None

    async def finalize(self, collection_id: uuid.UUID, user: RequestContext, rebuild_id: uuid.UUID) -> IndexRebuildOut:
        """The owner confirms the new index: the old one, kept for a rollback until now, is deleted."""
        rebuild = await self._owned(collection_id, user, rebuild_id, IndexRebuildStatus.SWAPPED)
        vector_store.delete_next_index(collection_id)
        rebuild.status = IndexRebuildStatus.FINALIZED
        rebuild.finished_at = datetime.now(UTC)
        await self.db.commit()
        return IndexRebuildOut.model_validate(rebuild)

    async def rollback(self, collection_id: uuid.UUID, user: RequestContext, rebuild_id: uuid.UUID) -> IndexRebuildOut:
        """Back to the old index, in one swap again: search returns to the previous model. The chosen
        model stays configured, so the collection is shown as still needing a rebuild."""
        rebuild = await self._owned(collection_id, user, rebuild_id, IndexRebuildStatus.SWAPPED)
        vector_store.swap_with_next(collection_id)
        settings = (await self.collections.get_by_id(collection_id)).settings
        settings.index_embedding_model = (
            None if rebuild.previous_model == settings.embedding_model else rebuild.previous_model
        )
        settings.reindex_required = settings.embedding_model != rebuild.previous_model
        rebuild.status = IndexRebuildStatus.ROLLED_BACK
        rebuild.finished_at = datetime.now(UTC)
        await self.db.commit()
        vector_store.delete_next_index(collection_id)
        # The old index missed whatever was written since the swap: the job reconciles it once.
        task_id = str(uuid.uuid4())
        await self.tasks.create(task_id, REBUILD_INDEX_TASK, user.user_id, collection_id=collection_id)
        await self.db.commit()
        try:
            result_id = enqueue_rebuild_index(str(rebuild.id), task_id=task_id)
        except Exception as exc:
            await self.tasks.set_status(task_id, TaskStatus.FAILURE, str(exc))
            await self.db.commit()
            raise
        await self.tasks.rename_celery_task_id(task_id, result_id)
        await self.db.commit()
        return IndexRebuildOut.model_validate(rebuild)

    # -- the worker's side ------------------------------------------------------------------------

    async def plan(self, rebuild_id: uuid.UUID) -> RebuildPlanOut:
        """What the index being worked on still lacks: the new one while building, the active one
        once swapped. Points that should no longer be there are deleted right away."""
        rebuild = await self._get(rebuild_id)
        model = _working_model(rebuild)
        if not await self._is_working(rebuild):
            return RebuildPlanOut(status=rebuild.status, collection_id=rebuild.collection_id, model=model, points=[])
        next_index = rebuild.status == IndexRebuildStatus.BUILDING
        expected = await self.rebuilds.expected_points(rebuild.collection_id)
        indexed = vector_store.list_points(rebuild.collection_id, next_index=next_index)

        stale = [point_id for point_id in indexed if point_id not in expected]
        vector_store.delete_points(rebuild.collection_id, stale, next_index=next_index)
        missing = [
            RebuildPointOut(id=uuid.UUID(point_id), kind=kind, text=text)
            for point_id, (kind, text) in expected.items()
            if (point := indexed.get(point_id)) is None
            or point["text"] != text
            or point["model"] != model
            or point["kind"] != kind
        ]
        if rebuild.status != IndexRebuildStatus.ROLLED_BACK:
            rebuild.total_points = len(expected)
            rebuild.done_points = len(expected) - len(missing)
            await self.db.commit()
        return RebuildPlanOut(
            status=rebuild.status,
            collection_id=rebuild.collection_id,
            model=model,
            points=missing[:PLAN_LIMIT],
            remaining=len(missing),
        )

    async def submit(self, rebuild_id: uuid.UUID, model: str, points: list[RebuildPointIn]) -> int:
        """Stores the vectors the worker made. One made from a text that has changed since the plan
        is dropped - the next plan hands the new text out - so a stale vector never overwrites a
        fresher one. Returns how many were stored."""
        rebuild = await self._get(rebuild_id)
        if not await self._is_working(rebuild):
            raise RebuildStateError(str(rebuild_id))
        if model != _working_model(rebuild):
            raise RebuildStateError(f"vectors made with {model}, the rebuild is for {_working_model(rebuild)}")
        current = await self.rebuilds.current_texts([point.id for point in points])
        kept = [
            (point.kind, point.id, point.text, point.embedding)
            for point in points
            if current.get(str(point.id)) == point.text
        ]
        vector_store.upsert_points(
            rebuild.collection_id, kept, model, next_index=rebuild.status == IndexRebuildStatus.BUILDING
        )
        return len(kept)

    async def swap(self, rebuild_id: uuid.UUID) -> bool:
        """Swaps the new index in once it holds everything - False when a plan still has work (a
        document was added since), the worker then carries on. The active model becomes the new one
        in the same step, so queries and new vectors match the index they now hit."""
        rebuild = await self._get(rebuild_id)
        if rebuild.status != IndexRebuildStatus.BUILDING:
            return rebuild.status == IndexRebuildStatus.SWAPPED
        if (await self.plan(rebuild_id)).remaining:
            return False
        if not vector_store.next_index_exists(rebuild.collection_id):
            # Nothing to index at all (an empty collection): no index to swap, only the model changes.
            pass
        else:
            vector_store.swap_with_next(rebuild.collection_id)
        settings = (await self.collections.get_by_id(rebuild.collection_id)).settings
        # The owner may have picked yet another model while this one was building: still required then.
        settings.index_embedding_model = (
            None if settings.embedding_model == rebuild.target_model else rebuild.target_model
        )
        settings.reindex_required = settings.embedding_model != rebuild.target_model
        rebuild.status = IndexRebuildStatus.SWAPPED
        rebuild.swapped_at = datetime.now(UTC)
        await self.db.commit()
        return True

    async def fail(self, rebuild_id: uuid.UUID, error: str) -> None:
        """The build gave up: the active index never changed, the half-built one is removed."""
        rebuild = await self._get(rebuild_id)
        if rebuild.status != IndexRebuildStatus.BUILDING:
            return
        rebuild.status = IndexRebuildStatus.FAILED
        rebuild.error = error[:2000]
        rebuild.finished_at = datetime.now(UTC)
        await self.db.commit()
        vector_store.delete_next_index(rebuild.collection_id)

    # -- helpers ----------------------------------------------------------------------------------

    async def _get(self, rebuild_id: uuid.UUID) -> IndexRebuild:
        rebuild = await self.rebuilds.get(rebuild_id)
        if rebuild is None:
            raise RebuildNotFoundError(str(rebuild_id))
        return rebuild

    async def _is_working(self, rebuild: IndexRebuild) -> bool:
        """Whether the rebuild still has an index to bring up to date. A rolled-back one has the old
        index back, as long as no other rebuild has replaced it since."""
        if rebuild.status in ACTIVE_REBUILD_STATUSES:
            return True
        if rebuild.status != IndexRebuildStatus.ROLLED_BACK:
            return False
        models = await self.collections.get_embedding_models([rebuild.collection_id])
        return models.get(rebuild.collection_id) == rebuild.previous_model and (
            await self.rebuilds.get_active(rebuild.collection_id) is None
        )

    async def _owned(
        self, collection_id: uuid.UUID, user: RequestContext, rebuild_id: uuid.UUID, status: IndexRebuildStatus
    ) -> IndexRebuild:
        if await self.collections.get(collection_id, user.user_id) is None:
            raise CollectionNotFoundError(str(collection_id))
        rebuild = await self.rebuilds.get(rebuild_id)
        if rebuild is None or rebuild.collection_id != collection_id:
            raise RebuildNotFoundError(str(rebuild_id))
        if rebuild.status != status:
            raise RebuildStateError(str(rebuild_id))
        return rebuild
