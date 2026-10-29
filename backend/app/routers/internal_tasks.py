from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LoggingSettings, TaskSettings
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.document_repository import DocumentRepository
from app.repositories.task_log_repository import TaskLogRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.internal_pipeline import (
    ExecutionMetricIn,
    TaskCreate,
    TaskLogEntriesIn,
    TaskLogsUpdate,
    TaskStatusUpdate,
)
from app.services.usage_service import UsageService

_logging_settings = LoggingSettings()
_task_settings = TaskSettings()

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


@router.post("/tasks", summary="Record a task the worker just dispatched", status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    documents = DocumentRepository(db)
    tasks = TaskRepository(db)

    document = await documents.get_with_collection(body.document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # The document's collection has the owner this task should be scoped to -
    # the worker only ever knows document/collection ids, never a Keycloak sub.
    owner_id = document.collection.owner_id

    parent_id = None
    if body.parent_celery_task_id is not None:
        parent = await tasks.get_by_celery_id(body.parent_celery_task_id)
        parent_id = parent.id if parent is not None else None

    await tasks.create(
        celery_task_id=body.celery_task_id,
        task_name=body.task_name,
        owner_id=owner_id,
        document_id=document.id,
        collection_id=document.collection_id,
        parent_id=parent_id,
    )
    await db.commit()
    return {"status": "ok"}


@router.patch(
    "/tasks/{celery_task_id}/status",
    summary="Record what a worker reports about a task as it runs it",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_task_status(
    celery_task_id: str, body: TaskStatusUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    # A task with no Task row (the beat's, the agent's runs) is a no-op: the worker reports every
    # task it runs, and only some of them are recorded here.
    await TaskRepository(db).set_status(celery_task_id, body.status, body.error)
    await db.commit()


@router.post("/tasks/reap", summary="Mark the tasks stuck running past their timeout as failed (run by the beat)")
async def reap_stuck_tasks(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, int]:
    before = datetime.now(UTC) - timedelta(hours=_task_settings.TASK_STUCK_AFTER_HOURS)
    reaped = await TaskRepository(db).reap_stuck(before)
    await db.commit()
    return {"reaped": reaped}


@router.post(
    "/task-logs",
    summary="Record lines a worker logged while running its tasks, sent a few at a time as they run",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_task_logs(body: TaskLogEntriesIn, db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    await TaskLogRepository(db).add_many([entry.model_dump() for entry in body.entries])
    await db.commit()


@router.post(
    "/execution-metrics",
    summary="Record the time, CPU and memory a worker task, or a step of the agent, used - sent when it ends",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_execution_metric(body: ExecutionMetricIn, db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    await UsageService(db).record_execution(body)


@router.delete("/task-logs", summary="Purge the task log lines past their retention (run by the beat)")
async def purge_task_logs(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, int]:
    before = datetime.now(UTC) - timedelta(days=_logging_settings.TASK_LOG_RETENTION_DAYS)
    deleted = await TaskLogRepository(db).purge(before)
    await db.commit()
    return {"deleted": deleted}


@router.patch(
    "/tasks/{celery_task_id}/logs",
    summary="Report a task's whole log output at once (workers before #305, while they roll out)",
    deprecated=True,
)
async def update_task_logs(
    celery_task_id: str, body: TaskLogsUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    tasks = TaskRepository(db)
    task = await tasks.get_by_celery_id(celery_task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if body.logs:
        await TaskLogRepository(db).add_many(
            [
                {
                    "celery_task_id": celery_task_id,
                    "task_name": task.task_name,
                    "document_id": task.document_id,
                    "collection_id": task.collection_id,
                    "ts": datetime.now(UTC),
                    "level": "INFO",
                    "message": body.logs,
                }
            ]
        )
    await db.commit()
    return {"status": "ok"}
