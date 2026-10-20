import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.collection_import import (
    CollectionImportInternalOut,
    CollectionImportOut,
    CollectionImportResult,
    ImportedCollectionCreate,
    ImportedCollectionOut,
    ImportedDocumentCreate,
)
from app.services.collection_hierarchy_service import HierarchyError
from app.services.collection_import_service import (
    ArchiveTooLargeError,
    CollectionImportNotFoundError,
    CollectionImportService,
    ConversationNotFoundError,
    ImportTargetError,
    InvalidArchiveError,
)
from app.services.collection_service import ParentCollectionNotFoundError

router = APIRouter(tags=["Collection imports"])
internal_router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


def get_collection_import_service(db: Annotated[AsyncSession, Depends(get_db)]) -> CollectionImportService:
    return CollectionImportService(db)


ServiceDep = Annotated[CollectionImportService, Depends(get_collection_import_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")


@router.post(
    "/collection-imports",
    summary="Upload a ZIP and turn it into a collection and its sub-collections (#223)",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CollectionImportOut,
)
async def start_import(
    file: UploadFile,
    user: UserDep,
    service: ServiceDep,
    parent_id: Annotated[uuid.UUID | None, Form()] = None,
    conversation_id: Annotated[uuid.UUID | None, Form()] = None,
) -> CollectionImportOut:
    if parent_id is not None and conversation_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An import goes either under a collection or into a conversation, not both",
        )
    try:
        return await service.start(
            user,
            file.file,
            file.filename or "archive.zip",
            file.size,
            parent_id=parent_id,
            conversation_id=conversation_id,
        )
    except InvalidArchiveError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Not a ZIP archive") from error
    except ArchiveTooLargeError as error:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="The archive is too large") from error
    except ParentCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent collection not found") from error
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    except HierarchyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A ZIP can't be imported into this collection"
        ) from error


@router.get(
    "/collection-imports/{import_id}",
    summary="Where an import stands, and its summary once done",
    response_model=CollectionImportOut,
)
async def get_import(import_id: uuid.UUID, user: UserDep, service: ServiceDep) -> CollectionImportOut:
    try:
        return await service.get(import_id, user)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error


@internal_router.post(
    "/collection-imports/{import_id}/begin",
    summary="Mark an import as running and fetch what the worker needs to run it",
    response_model=CollectionImportInternalOut,
)
async def begin_import(import_id: uuid.UUID, service: ServiceDep) -> CollectionImportInternalOut:
    try:
        collection_import = await service.begin(import_id)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    return CollectionImportInternalOut(
        id=collection_import.id,
        archive_key=collection_import.archive_key,
        root_collection_id=collection_import.root_collection_id,
    )


@internal_router.post(
    "/collection-imports/{import_id}/collections",
    summary="Create the sub-collection a ZIP folder becomes",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportedCollectionOut,
)
async def create_imported_collection(
    import_id: uuid.UUID, body: ImportedCollectionCreate, service: ServiceDep
) -> ImportedCollectionOut:
    try:
        return ImportedCollectionOut(id=await service.create_sub_collection(import_id, body.parent_id, body.name))
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    except (ImportTargetError, HierarchyError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not a collection of this import") from error


@internal_router.post(
    "/collection-imports/{import_id}/documents",
    summary="Record a file of the ZIP, already stored in RustFS, as a document and queue it",
    status_code=status.HTTP_201_CREATED,
)
async def add_imported_document(
    import_id: uuid.UUID, body: ImportedDocumentCreate, service: ServiceDep
) -> dict[str, str]:
    try:
        document_id = await service.add_document(import_id, body.collection_id, body.name, body.storage_key)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    except ImportTargetError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not a collection of this import") from error
    return {"id": str(document_id)}


@internal_router.put("/collection-imports/{import_id}/result", summary="Report how an import ended")
async def finish_import(import_id: uuid.UUID, body: CollectionImportResult, service: ServiceDep) -> dict[str, str]:
    try:
        await service.finish(import_id, body)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    return {"status": "ok"}
