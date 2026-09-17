import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.pagination import Page, PaginationParams
from app.schemas.task import TaskLogsOut, TaskOut
from app.services.task_service import TaskNotFoundError, TaskService

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


@router.get("/tasks/{task_id}/logs", summary="Fetch a task's full raw logs", response_model=TaskLogsOut)
async def get_task_logs(task_id: uuid.UUID, user: UserDep, service: ServiceDep) -> TaskLogsOut:
    try:
        return await service.get_logs(task_id, user)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from error
