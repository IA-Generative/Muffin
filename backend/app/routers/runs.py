import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.pagination import Page, PaginationParams
from app.schemas.run import RunCreate, RunEventOut, RunOut, RunResumeRequest
from app.services.run_service import ConversationNotFoundError, RunNotFoundError, RunNotWaitingError, RunService

router = APIRouter(tags=["Runs"])


def get_run_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RunService:
    return RunService(db)


ServiceDep = Annotated[RunService, Depends(get_run_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.post(
    "/runs",
    summary="Start a research agent run (returns immediately, doesn't wait for completion)",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunOut,
)
async def create_run(body: RunCreate, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.create_run(user, body)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.get("/runs/{run_id}", summary="Get a run's current status/result", response_model=RunOut)
async def get_run(run_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.get_run(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


@router.get(
    "/runs/{run_id}/events",
    summary="List a run's structured progress events, oldest first (poll with `since` for incremental updates)",
    response_model=Page[RunEventOut],
)
async def list_run_events(
    run_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
    since: uuid.UUID | None = None,
) -> Page[RunEventOut]:
    try:
        return await service.list_events(run_id, user, since, pagination)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


@router.post(
    "/runs/{run_id}/resume",
    summary="Answer a run's pending clarification question and continue it (only valid while "
    "status is waiting_for_user)",
    response_model=RunOut,
)
async def resume_run(run_id: uuid.UUID, body: RunResumeRequest, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.resume_run(run_id, user, body.answer)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    except RunNotWaitingError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run is not waiting for a clarification"
        ) from error


@router.post(
    "/runs/{run_id}/cancel",
    summary="Request cancellation of a run (cooperative - nodes check this at key points, it isn't instant)",
    response_model=RunOut,
)
async def cancel_run(run_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.cancel_run(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
