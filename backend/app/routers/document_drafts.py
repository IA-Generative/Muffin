import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.routers.living_documents import http_error as living_http_error
from app.schemas.document import DocumentOut
from app.schemas.document_draft import DraftCreate, DraftOut
from app.services.collection_service import CollectionNotEditableError, CollectionNotFoundError
from app.services.document_draft_service import (
    DocumentDraftService,
    DraftBusyError,
    DraftExistsError,
    DraftNotFoundError,
    DraftNotReadyError,
    ImagesNeedOdtError,
    NothingToValidateError,
    NoUploadedImageError,
    UnknownImageError,
    UnsupportedImageError,
)
from app.services.document_upload_service import DocumentNotFoundError
from app.services.living_document_service import (
    DocumentLockedError,
    LockLostError,
    NotLivingDocumentError,
    RevisionConflictError,
)

router = APIRouter(tags=["Living document drafts"])


def get_draft_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DocumentDraftService:
    return DocumentDraftService(db)


ServiceDep = Annotated[DocumentDraftService, Depends(get_draft_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]

_HANDLED = (
    CollectionNotFoundError,
    CollectionNotEditableError,
    DocumentNotFoundError,
    NotLivingDocumentError,
    DocumentLockedError,
    RevisionConflictError,
    LockLostError,
    DraftNotFoundError,
    DraftExistsError,
    DraftBusyError,
    DraftNotReadyError,
    NothingToValidateError,
    UnknownImageError,
    UnsupportedImageError,
    ImagesNeedOdtError,
    NoUploadedImageError,
)

_CONFLICTS = {
    DraftExistsError: ("draft_exists", "Ce document a déjà un brouillon : validez-le ou refusez-le d'abord."),
    DraftBusyError: ("draft_busy", "Une modification est en cours sur ce brouillon."),
    DraftNotReadyError: ("draft_not_ready", "Le brouillon n'est pas prêt pour cette action."),
    NothingToValidateError: ("no_changes", "Le brouillon ne contient aucune modification à valider."),
    NoUploadedImageError: ("no_uploaded_image", "Aucune image à insérer : déposez d'abord un fichier."),
}


def http_error(error: Exception) -> HTTPException:
    if isinstance(error, DraftNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "No draft for this document")
    if isinstance(error, UnknownImageError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "No such pending image")
    if isinstance(error, UnsupportedImageError):
        return HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PNG, JPEG and GIF images up to 10 MB are accepted"
        )
    if isinstance(error, ImagesNeedOdtError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Images can only be added to an ODT document")
    for kind, (code, message) in _CONFLICTS.items():
        if isinstance(error, kind):
            return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})
    return living_http_error(error)


@router.post(
    "/collections/{collection_id}/documents/{document_id}/draft",
    summary="Ask for an edit of a living document: a worker produces a draft to validate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DraftOut,
)
async def create_draft(
    collection_id: uuid.UUID, document_id: uuid.UUID, body: DraftCreate, user: UserDep, service: ServiceDep
) -> DraftOut:
    try:
        return await service.create(collection_id, user, document_id, body.prompt)
    except _HANDLED as error:
        raise http_error(error) from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/draft",
    summary="The document's draft and where its job stands - polling it keeps the draft alive",
    response_model=DraftOut,
)
async def get_draft(collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep) -> DraftOut:
    try:
        return await service.get_current(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/draft/preview",
    summary="The draft's preview: a PDF for an ODT, the text for a Markdown (streamed, never a storage URL)",
)
async def get_draft_preview(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> Response:
    try:
        content, media_type = await service.preview(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post(
    "/collections/{collection_id}/documents/{document_id}/draft/adjust",
    summary="Give a new instruction on top of the current draft",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DraftOut,
)
async def adjust_draft(
    collection_id: uuid.UUID, document_id: uuid.UUID, body: DraftCreate, user: UserDep, service: ServiceDep
) -> DraftOut:
    try:
        return await service.adjust(collection_id, user, document_id, body.prompt)
    except _HANDLED as error:
        raise http_error(error) from error


@router.put(
    "/collections/{collection_id}/documents/{document_id}/draft/images/{image_id}",
    summary="Upload the file for one of the draft's pending image spots (nothing is inserted yet)",
    response_model=DraftOut,
)
async def upload_draft_image(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    image_id: str,
    file: UploadFile,
    user: UserDep,
    service: ServiceDep,
) -> DraftOut:
    try:
        return await service.upload_image(
            collection_id, user, document_id, image_id, await file.read(), file.content_type or ""
        )
    except _HANDLED as error:
        raise http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/{document_id}/draft/images/insert",
    summary="Put every uploaded image into the draft and render a new preview",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DraftOut,
)
async def insert_draft_images(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> DraftOut:
    try:
        return await service.insert_images(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/{document_id}/draft/validate",
    summary="Accept the draft: it becomes the document's next revision and the document is reindexed",
    response_model=DocumentOut,
)
async def validate_draft(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> DocumentOut:
    try:
        return await service.validate(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error


@router.delete(
    "/collections/{collection_id}/documents/{document_id}/draft",
    summary="Refuse the draft: it and its files are deleted and the document is unlocked",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def refuse_draft(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> Response:
    try:
        await service.refuse(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
