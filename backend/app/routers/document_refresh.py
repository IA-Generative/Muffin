import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.document import (
    ContentHashIn,
    RefreshScheduleOut,
    RefreshScheduleUpdate,
    UrlFetchReportOut,
    UrlRefreshClaimOut,
)
from app.services.collection_service import CollectionNotFoundError
from app.services.document_refresh_service import DocumentRefreshService, NotUrlDocumentError
from app.services.document_upload_service import DocumentNotFoundError

# The scheduled refresh of a URL document (#19): the owner sets when its page is fetched again
# (`router`), the periodic scan in worker/document_process claims what is due and reports what it
# fetched (`internal_router`).
router = APIRouter(tags=["Documents"])
internal_router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


def get_refresh_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DocumentRefreshService:
    return DocumentRefreshService(db)


ServiceDep = Annotated[DocumentRefreshService, Depends(get_refresh_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _not_found(error: Exception) -> HTTPException:
    if isinstance(error, CollectionNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")


@router.get(
    "/collections/{collection_id}/documents/{document_id}/refresh-schedule",
    summary="When a URL document's page is fetched again, and when it last was",
    response_model=RefreshScheduleOut,
)
async def get_refresh_schedule(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> RefreshScheduleOut:
    try:
        return await service.get_schedule(collection_id, user, document_id)
    except (CollectionNotFoundError, DocumentNotFoundError) as error:
        raise _not_found(error) from error


@router.put(
    "/collections/{collection_id}/documents/{document_id}/refresh-schedule",
    summary="Set (or, with null, stop) the automatic refresh of a URL document: its page is fetched "
    "again once, every day, on some days of the week or every N minutes, and the document reprocessed "
    "when the page changed",
    response_model=RefreshScheduleOut,
)
async def set_refresh_schedule(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    body: RefreshScheduleUpdate,
    user: UserDep,
    service: ServiceDep,
) -> RefreshScheduleOut:
    try:
        return await service.set_schedule(collection_id, user, document_id, body.schedule)
    except (CollectionNotFoundError, DocumentNotFoundError) as error:
        raise _not_found(error) from error
    except NotUrlDocumentError as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "not_url_document", "message": "Seul un document ajouté depuis une URL peut être rafraîchi."},
        ) from error


@internal_router.post(
    "/url-refresh/claim",
    summary="Claim the URL documents due for a refresh (each one's next run moves forward)",
    response_model=UrlRefreshClaimOut,
)
async def claim_url_refresh(service: ServiceDep) -> UrlRefreshClaimOut:
    return UrlRefreshClaimOut(document_ids=await service.claim_due())


@internal_router.post(
    "/documents/{document_id}/url-refresh",
    summary="Report a refresh check: the hash of the page as fetched now - reprocesses the document "
    "when it differs from what is indexed",
    response_model=UrlFetchReportOut,
)
async def report_url_fetch(document_id: uuid.UUID, body: ContentHashIn, service: ServiceDep) -> UrlFetchReportOut:
    try:
        return UrlFetchReportOut(changed=await service.report_fetch(document_id, body.content_hash))
    except DocumentNotFoundError as error:
        raise _not_found(error) from error


@internal_router.put(
    "/documents/{document_id}/content-hash",
    summary="Record the hash of the page a URL document was just indexed from (and where the file it "
    "served is stored, if any)",
)
async def set_content_hash(document_id: uuid.UUID, body: ContentHashIn, service: ServiceDep) -> dict[str, str]:
    try:
        await service.set_content_hash(document_id, body.content_hash, body.storage_key)
    except DocumentNotFoundError as error:
        raise _not_found(error) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    return {"status": "ok"}
