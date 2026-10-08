from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.document_draft import DraftFailureIn, DraftResultIn
from app.services.document_draft_service import DocumentDraftService

# How worker/document_edit tells the backend a job finished - the worker keeps no state of its own,
# the draft lives here. Keyed by the Celery task id the backend chose (and stored) before sending.
router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


@router.patch("/document-drafts/{celery_task_id}/result", summary="Report a finished edit or image-insertion job")
async def report_result(
    celery_task_id: str, body: DraftResultIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    await DocumentDraftService(db).record_result(celery_task_id, body)
    return {"status": "ok"}


@router.patch("/document-drafts/{celery_task_id}/failure", summary="Report a failed edit or image-insertion job")
async def report_failure(
    celery_task_id: str, body: DraftFailureIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    await DocumentDraftService(db).record_failure(celery_task_id, body.error)
    return {"status": "ok"}
