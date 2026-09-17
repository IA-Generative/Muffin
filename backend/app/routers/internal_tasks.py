from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.document_repository import DocumentRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.internal_pipeline import TaskCreate, TaskLogsUpdate

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


@router.patch("/tasks/{celery_task_id}/logs", summary="Report a task's raw log output")
async def update_task_logs(
    celery_task_id: str, body: TaskLogsUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    tasks = TaskRepository(db)
    task = await tasks.get_by_celery_id(celery_task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await tasks.set_logs(task, body.logs)
    await db.commit()
    return {"status": "ok"}
