import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.document import (
    DocumentLockGrantOut,
    DocumentLockOut,
    DocumentOut,
    DocumentRevisionOut,
    MarkdownDocumentCreate,
)
from app.services.collection_service import CollectionNotFoundError
from app.services.document_upload_service import DocumentNotFoundError
from app.services.living_document_service import (
    DocumentLockedError,
    FormatMismatchError,
    LivingDocumentService,
    LockLostError,
    NotLivingDocumentError,
    RevisionConflictError,
    RevisionNotFoundError,
    UnsupportedFormatError,
)

router = APIRouter(tags=["Living documents"])


def get_living_document_service(db: Annotated[AsyncSession, Depends(get_db)]) -> LivingDocumentService:
    return LivingDocumentService(db)


ServiceDep = Annotated[LivingDocumentService, Depends(get_living_document_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]
# The holder's proof of lock ownership, returned by POST .../lock and presented on every write
# (and on renew/release) - see LivingDocumentService.acquire_lock.
LockTokenHeader = Annotated[str | None, Header(alias="X-Document-Lock-Token")]


def http_error(error: Exception) -> HTTPException:
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
    if isinstance(error, DocumentLockedError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "document_locked",
                "locked_by_display": error.lock.locked_by_display,
                "expires_at": error.lock.expires_at.isoformat(),
                "held_by_me": error.lock.held_by_me,
            },
        )
    if isinstance(error, RevisionConflictError):
        return HTTPException(
            status.HTTP_409_CONFLICT, {"code": "revision_conflict", "current_revision": error.current_revision}
        )
    if isinstance(error, LockLostError):
        return HTTPException(status.HTTP_409_CONFLICT, {"code": "lock_lost"})
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
    DocumentLockedError,
    RevisionConflictError,
    LockLostError,
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
        raise http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/living/markdown",
    summary="Create a Markdown living document from scratch (name + content, no upload)",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_markdown_document(
    collection_id: uuid.UUID, body: MarkdownDocumentCreate, user: UserDep, service: ServiceDep
) -> DocumentOut:
    try:
        return await service.create_markdown(collection_id, user, body.name, body.content)
    except _HANDLED as error:
        raise http_error(error) from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/content",
    summary="Download a living document's file - the current revision, or ?revision=N",
)
async def download_living_document(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep, revision: int | None = None
) -> Response:
    try:
        content, filename, media_type = await service.download(collection_id, user, document_id, revision)
    except _HANDLED as error:
        raise http_error(error) from error
    # filename* (RFC 5987) carries accents/spaces safely; the ASCII filename is the fallback.
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


@router.put(
    "/collections/{collection_id}/documents/{document_id}/content",
    summary="Replace a living document's file with a new revision and reindex that document only",
    response_model=DocumentOut,
)
async def replace_living_document(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    file: UploadFile,
    base_revision: int,
    lock_token: LockTokenHeader = None,
) -> DocumentOut:
    try:
        return await service.replace(
            collection_id,
            user,
            document_id,
            file.filename or "document",
            await file.read(),
            file.content_type or "application/octet-stream",
            base_revision=base_revision,
            lock_token=lock_token,
        )
    except _HANDLED as error:
        raise http_error(error) from error


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
        raise http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/{document_id}/revisions/{number}/restore",
    summary="Make an older revision current again (appends a new revision, history is kept)",
    response_model=DocumentOut,
)
async def restore_revision(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    number: int,
    user: UserDep,
    service: ServiceDep,
    base_revision: int,
    lock_token: LockTokenHeader = None,
) -> DocumentOut:
    try:
        return await service.restore(
            collection_id, user, document_id, number, base_revision=base_revision, lock_token=lock_token
        )
    except _HANDLED as error:
        raise http_error(error) from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/lock",
    summary="Who is editing this living document, if anyone (null when unlocked or expired)",
    response_model=DocumentLockOut | None,
)
async def get_lock(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> DocumentLockOut | None:
    try:
        return await service.get_lock(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error


@router.post(
    "/collections/{collection_id}/documents/{document_id}/lock",
    summary="Take the soft edit lock; 409 with the holder's name if someone else has it",
    response_model=DocumentLockGrantOut,
)
async def acquire_lock(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> DocumentLockGrantOut:
    try:
        return await service.acquire_lock(collection_id, user, document_id)
    except _HANDLED as error:
        raise http_error(error) from error


@router.put(
    "/collections/{collection_id}/documents/{document_id}/lock",
    summary="Renew the lock for another TTL; 409 lock_lost if it already expired",
    response_model=DocumentLockOut,
)
async def renew_lock(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    lock_token: Annotated[str, Header(alias="X-Document-Lock-Token")],
) -> DocumentLockOut:
    try:
        return await service.renew_lock(collection_id, user, document_id, lock_token)
    except _HANDLED as error:
        raise http_error(error) from error


@router.delete(
    "/collections/{collection_id}/documents/{document_id}/lock",
    summary="Release the lock with its token, or break it with force=true (collection owner)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_lock(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    lock_token: LockTokenHeader = None,
    force: bool = False,
) -> Response:
    try:
        await service.release_lock(collection_id, user, document_id, lock_token, force=force)
    except _HANDLED as error:
        raise http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
