import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.internal_document import ChunkCreate, DocumentPageCreate, DocumentStatusUpdate, InternalDocumentOut
from app.services.document_service import DocumentNotFoundError, DocumentService

# Not user-facing: called by the document-processing worker, authenticated
# with a shared API key instead of a Keycloak session.
router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


def get_document_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DocumentService:
    return DocumentService(db)


ServiceDep = Annotated[DocumentService, Depends(get_document_service)]


@router.get(
    "/documents/{document_id}",
    summary="Fetch a document's metadata (type, storage_key/name) for the worker to process",
    response_model=InternalDocumentOut,
)
async def get_document(document_id: uuid.UUID, service: ServiceDep) -> InternalDocumentOut:
    try:
        document = await service.get_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return InternalDocumentOut(
        id=document.id,
        collection_id=document.collection_id,
        name=document.name,
        type=document.type,
        status=document.status,
        storage_key=document.storage_key,
    )


@router.patch("/documents/{document_id}/status", summary="Report processing progress/status/error")
async def update_document_status(
    document_id: uuid.UUID, update: DocumentStatusUpdate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.update_status(document_id, update)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.post(
    "/documents/{document_id}/pages",
    summary="Record one page of extracted content",
    status_code=status.HTTP_201_CREATED,
)
async def create_document_page(document_id: uuid.UUID, page: DocumentPageCreate, service: ServiceDep) -> dict[str, str]:
    try:
        await service.add_page(document_id, page)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.post(
    "/documents/{document_id}/chunks",
    summary="Record one chunk (with liteparse bbox/layout extras, if any)",
    status_code=status.HTTP_201_CREATED,
)
async def create_document_chunk(document_id: uuid.UUID, chunk: ChunkCreate, service: ServiceDep) -> dict[str, str]:
    try:
        await service.add_chunk(document_id, chunk)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}
