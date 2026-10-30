import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.owui_sync_run_repository import OwuiSyncRunRepository
from app.schemas.owui_sync import OwuiSyncRunIn

router = APIRouter(
    prefix="/internal/owui-sync",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


@router.put(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Report a synchronisation with Open WebUI: started, ended with its account, or failed",
)
async def report_run(run_id: uuid.UUID, body: OwuiSyncRunIn, db: Annotated[AsyncSession, Depends(get_db)]) -> Response:
    await OwuiSyncRunRepository(db).report(
        run_id, body.status, body.started_at, body.account, body.error, datetime.now(UTC)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
