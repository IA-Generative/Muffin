import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.document import DocumentOut, FilingCandidateOut, FilingDecision
from app.services.collection_service import CollectionNotFoundError
from app.services.document_upload_service import (
    DocumentNotFoundError,
    DocumentUploadService,
    InvalidFilingDecisionError,
)

router = APIRouter(tags=["Filing"])


def get_document_upload_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentUploadService:
    return DocumentUploadService(db)


ServiceDep = Annotated[DocumentUploadService, Depends(get_document_upload_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/filing/documents",
    summary="Files the current user uploaded that still aren't in a permanent collection they "
    'control (§122) - the "Fichiers à ranger" review page',
    response_model=list[FilingCandidateOut],
)
async def list_files_to_file(user: UserDep, service: ServiceDep) -> list[FilingCandidateOut]:
    return await service.list_files_to_file(user)


@router.post(
    "/filing/documents/upload",
    summary="Upload a file straight to the review page, with no conversation at all (§122 "
    "follow-up) - lands in the uploader's own standalone holding collection until filed",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_standalone_document(file: UploadFile, user: UserDep, service: ServiceDep) -> DocumentOut:
    content = await file.read()
    return await service.upload_standalone_for_filing(
        user, file.filename, content, file.content_type or "application/octet-stream"
    )


@router.post(
    "/filing/documents/{document_id}/decision",
    summary="Accept a filing suggestion, file into a different collection, or dismiss - the "
    "user's answer to a filing suggestion (§122), from the chat notification or the review page",
    response_model=DocumentOut,
)
async def decide_filing(
    document_id: uuid.UUID, body: FilingDecision, user: UserDep, service: ServiceDep
) -> DocumentOut:
    try:
        return await service.decide_filing(
            document_id, user, action=body.action, target_collection_id=body.target_collection_id
        )
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except InvalidFilingDecisionError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filing decision") from error
