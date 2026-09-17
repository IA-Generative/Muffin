import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.document import DocumentOut, DocumentUrlCreate
from app.services.collection_service import CollectionNotFoundError
from app.services.document_upload_service import DocumentNotFoundError, DocumentUploadService

router = APIRouter(tags=["Documents"])


def get_document_upload_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DocumentUploadService:
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


@router.post(
    "/collections/{collection_id}/documents/file",
    summary="Upload a file, storing it in RustFS and queuing it for processing",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_file_document(
    collection_id: uuid.UUID, user: UserDep, service: ServiceDep, file: UploadFile
) -> DocumentOut:
    try:
        content = await file.read()
        return await service.create_file_document(
            collection_id, user, file.filename or "document", content, file.content_type or "application/octet-stream"
        )
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/collections/{collection_id}/documents/url",
    summary="Register a URL to scrape and queue it for processing",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def create_url_document(
    collection_id: uuid.UUID, body: DocumentUrlCreate, user: UserDep, service: ServiceDep
) -> DocumentOut:
    try:
        return await service.create_url_document(collection_id, user, body.url)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/collections/{collection_id}/documents/reindex",
    summary="Clear and re-queue every document in a collection (e.g. after an embedding model change)",
    response_model=list[DocumentOut],
)
async def reindex_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[DocumentOut]:
    try:
        return await service.reindex_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


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
