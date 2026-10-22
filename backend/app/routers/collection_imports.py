import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.collection_import import (
    AttachDecision,
    CollectionImportInternalOut,
    CollectionImportOut,
    CollectionImportResult,
    ImportBatchDone,
    ImportBatchDoneOut,
    ImportBatchesBegin,
    ImportedCollectionCreate,
    ImportedCollectionOut,
    ImportedDocumentCheck,
    ImportedDocumentCheckOut,
    ImportedDocumentCreate,
    ImportedDocumentOut,
)
from app.schemas.document import ReprocessedOut
from app.services.collection_hierarchy_service import HierarchyError
from app.services.collection_import_service import (
    CollectionImportNotFoundError,
    CollectionImportService,
    ConversationNotFoundError,
    ImportTargetError,
    InvalidArchiveError,
    InvalidAttachDecisionError,
)
from app.services.collection_service import ParentCollectionNotFoundError
from app.services.import_processing_queue import ImportProcessingQueue

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
    except ParentCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent collection not found") from error
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    except HierarchyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A ZIP can't be imported into this collection"
        ) from error


@router.get(
    "/collection-imports",
    summary="The current user's imports, most recent first - optionally only one conversation's, or "
    "only those with an attach suggestion still awaiting an answer",
    response_model=list[CollectionImportOut],
)
async def list_imports(
    user: UserDep,
    service: ServiceDep,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
    awaiting_attachment: Annotated[bool, Query()] = False,
) -> list[CollectionImportOut]:
    return await service.list(user, conversation_id=conversation_id, awaiting_attachment=awaiting_attachment)


@router.post(
    "/collection-imports/{import_id}/attach",
    summary="Answer an attach suggestion: accept it, choose another collection, or dismiss it",
    response_model=CollectionImportOut,
)
async def decide_attachment(
    import_id: uuid.UUID, decision: AttachDecision, user: UserDep, service: ServiceDep
) -> CollectionImportOut:
    try:
        return await service.decide_attachment(import_id, user, decision)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    except InvalidAttachDecisionError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to attach for this decision"
        ) from error
    except ParentCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent collection not found") from error
    except HierarchyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The collection can't be attached there"
        ) from error


@router.post(
    "/collection-imports/{import_id}/reprocess-failed",
    summary="Relaunch the indexing of the documents of an import that ended in error (#340)",
    response_model=ReprocessedOut,
)
async def reprocess_failed_import_documents(import_id: uuid.UUID, user: UserDep, service: ServiceDep) -> ReprocessedOut:
    try:
        return ReprocessedOut(reprocessed=await service.reprocess_failed(import_id, user))
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error


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
    "/collection-imports/{import_id}/documents/check",
    summary="Whether a file of the ZIP is already in the collection it would go to, by its hash (#300)",
    response_model=ImportedDocumentCheckOut,
)
async def check_imported_document(
    import_id: uuid.UUID, body: ImportedDocumentCheck, service: ServiceDep
) -> ImportedDocumentCheckOut:
    try:
        return ImportedDocumentCheckOut(
            duplicate=await service.has_document(import_id, body.collection_id, body.content_hash)
        )
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    except ImportTargetError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not a collection of this import") from error


@internal_router.post(
    "/collection-imports/{import_id}/documents",
    summary="Record a file of the ZIP, already stored in RustFS, as a document and queue it",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportedDocumentOut,
)
async def add_imported_document(
    import_id: uuid.UUID, body: ImportedDocumentCreate, service: ServiceDep
) -> ImportedDocumentOut:
    try:
        document_id = await service.add_document(
            import_id, body.collection_id, body.name, body.storage_key, body.content_hash
        )
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    except ImportTargetError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not a collection of this import") from error
    return ImportedDocumentOut(id=document_id, duplicate=document_id is None)


@internal_router.post(
    "/collection-imports/{import_id}/batches/begin",
    summary="A big archive is read in batches of files (#334): announce them, with the planner's part of the summary",
)
async def begin_import_batches(import_id: uuid.UUID, body: ImportBatchesBegin, service: ServiceDep) -> dict[str, str]:
    try:
        await service.begin_batches(import_id, body.expected, body.plan)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    return {"status": "ok"}


@internal_router.post(
    "/collection-imports/{import_id}/batches/{key}/done",
    summary="A batch of files of the ZIP is done: answers where the import is, and - for the one batch that "
    "completed it - the summary of the whole",
    response_model=ImportBatchDoneOut,
)
async def import_batch_done(
    import_id: uuid.UUID, key: str, body: ImportBatchDone, service: ServiceDep
) -> ImportBatchDoneOut:
    try:
        return await service.batch_done(import_id, key, body)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error


@internal_router.put("/collection-imports/{import_id}/result", summary="Report how an import ended")
async def finish_import(import_id: uuid.UUID, body: CollectionImportResult, service: ServiceDep) -> dict[str, str]:
    try:
        await service.finish(import_id, body)
    except CollectionImportNotFoundError as error:
        raise _NOT_FOUND from error
    return {"status": "ok"}


@internal_router.post(
    "/collection-imports/release",
    summary="The sweep of the imports' windows (#335): releases, for each import with documents waiting, "
    "what its window allows - whatever freed a place without releasing the next document (a lost call)",
)
async def release_waiting_documents(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, int]:
    return {"released": await ImportProcessingQueue(db).release_waiting()}
