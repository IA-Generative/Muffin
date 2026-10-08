import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.run import Run
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.run_repository import RunRepository
from app.routers.document_drafts import _HANDLED, http_error
from app.schemas.document_draft import DraftOut
from app.schemas.internal_edit_request import EditableDocumentOut, EditRequestCreate
from app.services.document_draft_service import DocumentDraftService
from app.services.document_upload_service import DocumentNotFoundError
from app.services.editing_rights import can_edit

# How the research agent delegates an edit of a living document to the editing agent (#171): it asks
# the backend, which creates the draft (and its lock) and sends the job, then it follows the draft
# until the editing agent is done. The user is never taken from the request: it is the run's own
# snapshot (user, groups, administrator flag), so the agent can't act for anyone else, nor beyond
# what that user may do - the same rules as the user-facing API apply.
router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])

# How many documents the agent is shown to choose from - far more than anyone has, and bounded so a
# pathological collection can't blow up its prompt.
_MAX_EDITABLE_DOCUMENTS = 200
_SUMMARY_CHARS = 300


def _identity(run: Run) -> RequestContext:
    return RequestContext(
        user_id=run.user_id,
        email="",
        roles=[],
        is_admin=run.user_is_admin,
        first_name=run.user_display or "",
        groups=run.user_groups or [],
    )


async def _run(db: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await RunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get(
    "/runs/{run_id}/editable-documents",
    summary="The living documents the run's user may change",
    response_model=list[EditableDocumentOut],
)
async def list_editable_documents(
    run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[EditableDocumentOut]:
    run = await _run(db, run_id)
    user = _identity(run)
    collections = await CollectionRepository(db).list_all_accessible(user.user_id, user.groups)
    editable = {c.id: c for c in collections if can_edit(user, c) and not c.is_temporary}
    documents = await DocumentRepository(db).list_living_by_collections(list(editable))
    return [
        EditableDocumentOut(
            document_id=document.id,
            name=document.name,
            collection_id=document.collection_id,
            collection_name=editable[document.collection_id].name,
            summary=(document.summary or "")[:_SUMMARY_CHARS] or None,
        )
        for document in documents[:_MAX_EDITABLE_DOCUMENTS]
    ]


@router.post(
    "/runs/{run_id}/edit-requests",
    summary="Start an edit of a living document on the run's user's behalf",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DraftOut,
)
async def create_edit_request(
    run_id: uuid.UUID, body: EditRequestCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> DraftOut:
    run = await _run(db, run_id)
    user = _identity(run)
    document = await DocumentRepository(db).get(body.document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    try:
        return await DocumentDraftService(db).create(document.collection_id, user, document.id, body.prompt)
    except _HANDLED as error:
        raise http_error(error) from error


@router.get(
    "/runs/{run_id}/edit-requests/{document_id}",
    summary="Where the edit of a document stands - following it keeps the draft alive",
    response_model=DraftOut,
)
async def get_edit_request(
    run_id: uuid.UUID, document_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> DraftOut:
    run = await _run(db, run_id)
    document = await DocumentRepository(db).get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(DocumentNotFoundError(document_id)))
    try:
        return await DocumentDraftService(db).get_current(document.collection_id, _identity(run), document.id)
    except _HANDLED as error:
        raise http_error(error) from error
