import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.pagination import Page, PaginationParams
from app.schemas.task import TaskLogsOut, TaskOut
from app.services.task_service import LogsDocumentNotFoundError, TaskNotFoundError, TaskService

router = APIRouter(tags=["Tasks"])


def get_task_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TaskService:
    return TaskService(db)


ServiceDep = Annotated[TaskService, Depends(get_task_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/tasks",
    summary="List the current user's dispatched background task runs, most recent first",
    response_model=Page[TaskOut],
)
async def list_tasks(
    user: UserDep, service: ServiceDep, pagination: Annotated[PaginationParams, Depends()]
) -> Page[TaskOut]:
    return await service.list_tasks(user, pagination)


@router.post("/tasks/{task_id}/revoke", summary="Revoke a dispatched background task", response_model=TaskOut)
async def revoke_task(task_id: uuid.UUID, user: UserDep, service: ServiceDep) -> TaskOut:
    try:
        return await service.revoke(task_id, user)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from error


AfterQuery = Annotated[int, Query(ge=0, description="Only the lines after this one (the last `id` already read)")]
LevelQuery = Annotated[
    str | None, Query(description="Only the lines of this level or above (DEBUG, INFO, WARNING, ERROR...)")
]


@router.get(
    "/tasks/{task_id}/logs",
    summary="Fetch a task's log lines - from `after` on, to follow them live while it runs",
    response_model=TaskLogsOut,
)
async def get_task_logs(
    task_id: uuid.UUID, user: UserDep, service: ServiceDep, after: AfterQuery = 0, level: LevelQuery = None
) -> TaskLogsOut:
    try:
        return await service.get_logs(task_id, user, after=after, min_level=level)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/logs",
    summary="Fetch the log lines of every task of a document's pipeline, on one timeline",
    response_model=TaskLogsOut,
)
async def get_document_logs(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    after: AfterQuery = 0,
    level: LevelQuery = None,
) -> TaskLogsOut:
    try:
        return await service.get_document_logs(collection_id, document_id, user, after=after, min_level=level)
    except LogsDocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
