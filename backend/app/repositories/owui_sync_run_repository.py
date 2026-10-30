import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.document import Document
from app.models.group import ResourceSource
from app.models.index_rebuild import IndexRebuild, IndexRebuildStatus
from app.models.owui_sync_run import OwuiSyncRun

# The accounts kept: the page shows the latest, the rest is for whoever looks for what happened before.
KEPT_RUNS = 30


class OwuiSyncRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def report(
        self,
        run_id: uuid.UUID,
        status: str,
        started_at: datetime | None,
        account: dict | None,
        error: str | None,
        now: datetime,
    ) -> OwuiSyncRun:
        """An upsert: the worker reports a run when it starts and again when it ends, and a report that arrives
        twice, or the end before the start, changes nothing it should not. The start time is the first one given."""
        statement = insert(OwuiSyncRun).values(
            run_id=run_id,
            status=status,
            started_at=started_at or now,
            finished_at=None if status == "running" else now,
            account=account,
            error=error,
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[OwuiSyncRun.run_id],
                set_={
                    "status": statement.excluded.status,
                    "finished_at": statement.excluded.finished_at,
                    "account": statement.excluded.account,
                    "error": statement.excluded.error,
                },
                # A run that ended is not made to run again by a report that arrives late.
                where=(OwuiSyncRun.status == "running") | (statement.excluded.status != "running"),
            )
        )
        stale = select(OwuiSyncRun.run_id).order_by(OwuiSyncRun.started_at.desc()).offset(KEPT_RUNS)
        await self.db.execute(delete(OwuiSyncRun).where(OwuiSyncRun.run_id.in_(stale)))
        await self.db.flush()
        return await self.db.get(OwuiSyncRun, run_id, populate_existing=True)

    async def latest(self) -> OwuiSyncRun | None:
        result = await self.db.execute(select(OwuiSyncRun).order_by(OwuiSyncRun.started_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def copied_collections(self) -> list[tuple[Collection, int, int, bool]]:
        """The collections that come from another system, with how many documents and summaries they have and whether
        Muffin is rebuilding their index to take them over (#462), by name."""
        documents = (
            select(
                Document.collection_id,
                func.count(Document.id).label("documents"),
                func.count(Document.summary).label("summaries"),
            )
            .group_by(Document.collection_id)
            .subquery()
        )
        adopting = (
            select(IndexRebuild.collection_id)
            .where(IndexRebuild.status == IndexRebuildStatus.BUILDING, IndexRebuild.adopts.is_(True))
            .subquery()
        )
        rows = await self.db.execute(
            select(
                Collection,
                func.coalesce(documents.c.documents, 0),
                func.coalesce(documents.c.summaries, 0),
                Collection.id.in_(select(adopting.c.collection_id)),
            )
            .outerjoin(documents, documents.c.collection_id == Collection.id)
            .where(Collection.source != ResourceSource.MUFFIN)
            .order_by(Collection.name)
        )
        return [
            (collection, documents_, summaries, bool(is_adopting))
            for collection, documents_, summaries, is_adopting in rows.all()
        ]
