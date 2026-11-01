import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.memory import RunMemoryCommand, RunMemoryCommandOut, RunMemoryOut, RunMemoryUsed
from app.services.memory_service import MemoryService

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


def _unknown() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


@router.get("/runs/{run_id}/memory", summary="What a run may read of its person's memory (#284)")
async def read_memory(run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> RunMemoryOut:
    memory = await MemoryService(db).for_run(run_id)
    if memory is None:
        raise _unknown()
    return memory


@router.post("/runs/{run_id}/memory/used", status_code=status.HTTP_204_NO_CONTENT, summary="The items an answer used")
async def record_use(run_id: uuid.UUID, body: RunMemoryUsed, db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    if not await MemoryService(db).record_use(run_id, body.ids):
        raise _unknown()


@router.post("/runs/{run_id}/memory/command", summary="What the person asked of their memory in the chat")
async def run_command(
    run_id: uuid.UUID, body: RunMemoryCommand, db: Annotated[AsyncSession, Depends(get_db)]
) -> RunMemoryCommandOut:
    outcome = await MemoryService(db).command(run_id, body)
    if outcome is None:
        raise _unknown()
    return outcome
