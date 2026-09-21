import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.internal_document import (
    ChunkCreate,
    DocumentPageCreate,
    DocumentPageOut,
    DocumentStatusUpdate,
    InternalDocumentOut,
)
from app.schemas.internal_pipeline import (
    DocumentErrorUpdate,
    DocumentSummaryUpdate,
    DocumentTagsUpdate,
    TabularProfileCreate,
)
from app.services.document_service import DocumentNotFoundError, DocumentService

# Not user-facing: called by the document-processing worker, authenticated
# with a shared API key instead of a Keycloak session.
router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


def get_document_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentService:
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
        summary=document.summary,
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


@router.get(
    "/documents/{document_id}/pages",
    summary="Fetch a document's extracted pages, for chunking/summary/QA/extraction to read",
    response_model=list[DocumentPageOut],
)
async def list_document_pages(document_id: uuid.UUID, service: ServiceDep) -> list[DocumentPageOut]:
    try:
        pages = await service.list_pages(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return [DocumentPageOut(page_number=page.page_number, content=page.content) for page in pages]


@router.patch(
    "/documents/{document_id}/summary",
    summary="Report the generated summary for a document",
)
async def update_document_summary(
    document_id: uuid.UUID, update: DocumentSummaryUpdate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.set_summary(document_id, update.summary, update.embedding)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.patch(
    "/documents/{document_id}/error",
    summary="Report a pipeline-step error for a document",
)
async def update_document_error(
    document_id: uuid.UUID, update: DocumentErrorUpdate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.set_error(document_id, update.error)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.post(
    "/documents/{document_id}/suggest-filing",
    summary="Compute (best-effort) a filing suggestion for a conversation file, once its "
    "summary is ready - a no-op for a document outside a temporary collection (§122)",
)
async def suggest_filing(document_id: uuid.UUID, service: ServiceDep) -> dict[str, str]:
    try:
        await service.suggest_filing(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.put("/documents/{document_id}/tags", summary="Replace a document's generated tags")
async def replace_document_tags(
    document_id: uuid.UUID, update: DocumentTagsUpdate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.replace_tags(document_id, update.tags)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}


@router.post(
    "/documents/{document_id}/tabular-profile",
    summary="Persist the DuckDB-computed statistical profile of a tabular document",
    status_code=status.HTTP_201_CREATED,
)
async def set_tabular_profile(
    document_id: uuid.UUID, profile: TabularProfileCreate, service: ServiceDep
) -> dict[str, str]:
    try:
        await service.set_tabular_profile(document_id, profile)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    return {"status": "ok"}
