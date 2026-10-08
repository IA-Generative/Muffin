import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.document import DocumentOut, DocumentRevisionOut
from app.services.collection_service import CollectionNotFoundError
from app.services.document_upload_service import DocumentNotFoundError
from app.services.living_document_service import (
    FormatMismatchError,
    LivingDocumentService,
    NotLivingDocumentError,
    RevisionNotFoundError,
    UnsupportedFormatError,
)

router = APIRouter(tags=["Living documents"])


def get_living_document_service(db: Annotated[AsyncSession, Depends(get_db)]) -> LivingDocumentService:
    return LivingDocumentService(db)


ServiceDep = Annotated[LivingDocumentService, Depends(get_living_document_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, CollectionNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    if isinstance(error, DocumentNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if isinstance(error, RevisionNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
    if isinstance(error, NotLivingDocumentError):
        return HTTPException(status.HTTP_409_CONFLICT, "Not a living document")
    if isinstance(error, UnsupportedFormatError):
        return HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .odt and .md files are supported")
    if isinstance(error, FormatMismatchError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The new file must have the same format")
    raise error


_HANDLED = (
    CollectionNotFoundError,
    DocumentNotFoundError,
    RevisionNotFoundError,
    NotLivingDocumentError,
    UnsupportedFormatError,
    FormatMismatchError,
)


@router.post(
    "/collections/{collection_id}/documents/living",
    summary="Upload an ODT or Markdown file as a living document (first revision)",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_living_document(
    collection_id: uuid.UUID, user: UserDep, service: ServiceDep, file: UploadFile
) -> DocumentOut:
    try:
        return await service.create(
            collection_id,
            user,
            file.filename or "document",
            await file.read(),
            file.content_type or "application/octet-stream",
        )
    except _HANDLED as error:
        raise _http_error(error) from error


@router.put(
    "/collections/{collection_id}/documents/{document_id}/content",
    summary="Replace a living document's file with a new revision and reindex that document only",
    response_model=DocumentOut,
)
async def replace_living_document(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep, file: UploadFile
) -> DocumentOut:
    try:
        return await service.replace(
            collection_id,
            user,
            document_id,
            file.filename or "document",
            await file.read(),
            file.content_type or "application/octet-stream",
        )
    except _HANDLED as error:
        raise _http_error(error) from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/revisions",
    summary="List a living document's revisions, newest (current) first",
    response_model=list[DocumentRevisionOut],
)
async def list_revisions(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> list[DocumentRevisionOut]:
    try:
        return await service.list_revisions(collection_id, user, document_id)
    except _HANDLED as error:
        raise _http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/{document_id}/revisions/{number}/restore",
    summary="Make an older revision current again (appends a new revision, history is kept)",
    response_model=DocumentOut,
)
async def restore_revision(
    collection_id: uuid.UUID, document_id: uuid.UUID, number: int, user: UserDep, service: ServiceDep
) -> DocumentOut:
    try:
        return await service.restore(collection_id, user, document_id, number)
    except _HANDLED as error:
        raise _http_error(error) from error
