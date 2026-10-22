import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.collection import EntityOut, RelationOut
from app.schemas.document import (
    DocumentDetailOut,
    DocumentOut,
    DocumentPageOut,
    DocumentUrlCreate,
    TabularProfileOut,
)
from app.schemas.pagination import Page, PaginationParams
from app.services.collection_service import CollectionNotFoundError
from app.services.document_upload_service import (
    DocumentNotFoundError,
    DocumentUploadService,
    DuplicateDocumentError,
    FileTooLargeError,
)

router = APIRouter(tags=["Documents"])


def get_document_upload_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentUploadService:
    return DocumentUploadService(db)


ServiceDep = Annotated[DocumentUploadService, Depends(get_document_upload_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/collections/{collection_id}/documents",
    summary="List a collection's documents",
    response_model=list[DocumentOut],
)
async def list_documents(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[DocumentOut]:
    try:
        return await service.list_documents(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}",
    summary="Get one document's detail - summary, tags, page count",
    response_model=DocumentDetailOut,
)
async def get_document(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> DocumentDetailOut:
    try:
        return await service.get_document(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/pages/{page_number}/screenshot",
    summary="Stream a page's screenshot through the backend (never a direct/public storage URL)",
)
async def get_page_screenshot(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    page_number: int,
    user: UserDep,
    service: ServiceDep,
) -> Response:
    try:
        content, content_type = await service.get_page_screenshot(collection_id, user, document_id, page_number)
        return Response(content=content, media_type=content_type)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/pages",
    summary="List a document's pages (content + a same-backend screenshot URL, if any), paginated",
    response_model=Page[DocumentPageOut],
)
async def list_document_pages(
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[DocumentPageOut]:
    try:
        return await service.list_pages(collection_id, user, document_id, pagination)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/tabular-profile",
    summary="Get the tabular profile (stats, schema, classification) of a tabular document",
    response_model=TabularProfileOut | None,
)
async def get_tabular_profile(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> TabularProfileOut | None:
    try:
        return await service.get_tabular_profile(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/entities",
    summary="List entities actually mentioned in this document (not the whole collection's)",
    response_model=list[EntityOut],
)
async def list_document_entities(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> list[EntityOut]:
    try:
        return await service.list_entities(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error


@router.get(
    "/collections/{collection_id}/documents/{document_id}/relations",
    summary="List relations extracted from this document (not the whole collection's)",
    response_model=list[RelationOut],
)
async def list_document_relations(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> list[RelationOut]:
    try:
        return await service.list_relations(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error


def file_too_large(error: FileTooLargeError) -> HTTPException:
    """Only when DOCUMENT_MAX_UPLOAD_BYTES is set - by default, a file of any size is taken."""
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
        {
            "code": "file_too_large",
            "message": f"Le fichier dépasse la taille maximale acceptée ({error.max_bytes // (1024 * 1024)} Mo).",
        },
    )


def _duplicate(error: DuplicateDocumentError) -> HTTPException:
    """The collection already holds it (#300): the existing document is named so that the user can decide
    to add it anyway - which they can do, so this is a 409 to confirm and not a refusal."""
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "code": "duplicate_document",
            "message": "Ce document est déjà dans la collection.",
            "document": {"id": str(error.existing.id), "name": error.existing.name},
        },
    )


@router.post(
    "/collections/{collection_id}/documents/file",
    summary="Upload a file, storing it in RustFS and queuing it for processing - a 409 duplicate_document "
    "when the collection already has this file, unless allow_duplicate is set",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_file_document(
    collection_id: uuid.UUID, user: UserDep, service: ServiceDep, file: UploadFile, allow_duplicate: bool = False
) -> DocumentOut:
    try:
        return await service.create_file_document(
            collection_id,
            user,
            file.filename or "document",
            file.file,
            file.content_type or "application/octet-stream",
            allow_duplicate=allow_duplicate,
        )
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DuplicateDocumentError as error:
        raise _duplicate(error) from error
    except FileTooLargeError as error:
        raise file_too_large(error) from error


@router.post(
    "/collections/{collection_id}/documents/url",
    summary="Register a URL to scrape (an HTML page, or a file it serves) and queue it for processing, "
    "with when it is fetched again, if ever - a 409 duplicate_document when the collection already has this "
    "URL, unless allow_duplicate is set",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_url_document(
    collection_id: uuid.UUID,
    body: DocumentUrlCreate,
    user: UserDep,
    service: ServiceDep,
) -> DocumentOut:
    try:
        return await service.create_url_document(
            collection_id, user, body.url, body.refresh_schedule, allow_duplicate=body.allow_duplicate
        )
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except DuplicateDocumentError as error:
        raise _duplicate(error) from error


@router.delete(
    "/collections/{collection_id}/documents/{document_id}",
    summary="Delete a document and its RustFS objects (uploaded file, page screenshots)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(collection_id: uuid.UUID, document_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_document(collection_id, user, document_id)
    except (CollectionNotFoundError, DocumentNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
