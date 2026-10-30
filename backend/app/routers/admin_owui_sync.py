from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import tasks
from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.models.owui_sync_run import OwuiSyncRun
from app.repositories.owui_sync_run_repository import OwuiSyncRunRepository
from app.schemas.owui_sync import OwuiSyncRunOut, OwuiSyncStateOut, SyncedCollectionOut

router = APIRouter(prefix="/admin", tags=["Admin"])

# A synchronisation that has reported no end after this long did not end: a worker died with it. The longest ones
# copy a whole Open WebUI, which is minutes to a few hours.
STALLED_AFTER = timedelta(hours=6)


class OwuiSyncStarted(BaseModel):
    task_id: str


def require_admin(user: RequestContext) -> None:
    if not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only an administrator can use the synchronisation with Open WebUI"
        )


def _with_problems(run: OwuiSyncRun) -> bool:
    """Something went wrong in a run that ended: objects in error, a knowledge base that could not be listed or whose
    vectors do not match what Muffin will search with."""
    if run.status == "failed":
        return True
    account = run.account or {}
    return any(
        counts.get(key)
        for counts in (account.get("groups") or {}, account.get("knowledge_bases") or {}, account.get("files") or {})
        for key in ("errors", "unlisted", "inconsistent")
    )


def present(run: OwuiSyncRun, now: datetime) -> OwuiSyncRunOut:
    return OwuiSyncRunOut(
        run_id=run.run_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        account=run.account,
        error=run.error,
        stalled=run.status == "running" and now - run.started_at > STALLED_AFTER,
        with_problems=_with_problems(run),
    )


@router.post(
    "/owui-sync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a synchronisation with Open WebUI now",
)
async def start_owui_sync(user: Annotated[RequestContext, Depends(get_current_user)]) -> OwuiSyncStarted:
    require_admin(user)
    return OwuiSyncStarted(task_id=tasks.enqueue_sync_owui())


@router.get(
    "/owui-sync",
    summary="The latest synchronisation with Open WebUI and its account (None: there never was one)",
)
async def get_owui_sync(
    user: Annotated[RequestContext, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> OwuiSyncStateOut:
    require_admin(user)
    latest = await OwuiSyncRunRepository(db).latest()
    if latest is None:
        return OwuiSyncStateOut(latest=None, running=False)
    presented = present(latest, datetime.now(UTC))
    return OwuiSyncStateOut(latest=presented, running=presented.status == "running" and not presented.stalled)


@router.get(
    "/owui-sync/collections",
    summary="The collections copied from Open WebUI, with where each one is: copied, being taken over, or Muffin's",
)
async def list_synced_collections(
    user: Annotated[RequestContext, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> list[SyncedCollectionOut]:
    require_admin(user)
    return [
        SyncedCollectionOut(
            id=collection.id,
            name=collection.name,
            external_id=collection.external_id or "",
            state="adopted" if collection.is_adopted else "adopting" if adopting else "copied",
            document_count=documents,
            summary_count=summaries,
            synced_at=collection.synced_at,
            problems=collection.sync_problems or [],
        )
        for collection, documents, summaries, adopting in await OwuiSyncRunRepository(db).copied_collections()
    ]
