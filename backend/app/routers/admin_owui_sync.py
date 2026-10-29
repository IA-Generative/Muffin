from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import tasks
from app.core.security.factory import RequestContext, get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])


class OwuiSyncStarted(BaseModel):
    task_id: str


@router.post(
    "/owui-sync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a synchronisation with Open WebUI now",
)
async def start_owui_sync(user: Annotated[RequestContext, Depends(get_current_user)]) -> OwuiSyncStarted:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an administrator can start a synchronisation")
    return OwuiSyncStarted(task_id=tasks.enqueue_sync_owui())
