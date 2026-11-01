import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.run_repository import RunRepository
from app.schemas.tool import RunToolCallRequest, RunToolDefinitionsRequest, ToolCallRequest, ToolCallResult, ToolOut
from app.services.tool_service import ToolService

router = APIRouter(
    prefix="/internal/tools",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


async def _person_of(run_id: uuid.UUID, db: AsyncSession) -> tuple[str, list[str], uuid.UUID | None, str]:
    """Who a run is for, and what they asked - from the run row, which the agent cannot change by what it sends."""
    run = await RunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run.user_id, list(run.user_groups or []), run.conversation_id, run.query


@router.post("/definitions", summary="The tools the person of a run may use now, as the model is given them")
async def definitions(body: RunToolDefinitionsRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> list[ToolOut]:
    user_id, groups, conversation_id, query = await _person_of(body.run_id, db)
    return await ToolService(db).definitions(user_id, groups, conversation_id, query)


@router.post(
    "/call", summary="One call of a tool for the person of a run - never an error: a result with a stable code"
)
async def call(body: RunToolCallRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> ToolCallResult:
    user_id, groups, conversation_id, _query = await _person_of(body.run_id, db)
    return await ToolService(db).call(
        ToolCallRequest(
            user_id=user_id,
            groups=groups,
            conversation_id=conversation_id,
            run_id=body.run_id,
            ref=body.ref,
            arguments=body.arguments,
        )
    )
