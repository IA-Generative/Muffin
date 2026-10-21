import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.collection import QaPairCreate, QaPairOut, QaPairValidationUpdate
from app.services.collection_service import CollectionNotFoundError
from app.services.qa_pair_service import (
    GoldenPairNotValidatableError,
    QaPairNotFoundError,
    QaPairService,
    TooManyDocumentsError,
    UnknownDocumentError,
)

router = APIRouter(tags=["Question/answer pairs"])


def get_qa_pair_service(db: Annotated[AsyncSession, Depends(get_db)]) -> QaPairService:
    return QaPairService(db)


ServiceDep = Annotated[QaPairService, Depends(get_qa_pair_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _not_found(error: Exception) -> HTTPException:
    if isinstance(error, CollectionNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return HTTPException(status.HTTP_404_NOT_FOUND, "Question/answer pair not found")


@router.post(
    "/collections/{collection_id}/qa-pairs",
    summary="Write a question/answer pair: a reference the assistant answers from, or - with golden - a "
    "test question that is never embedded in the retriever and only used to measure it",
    status_code=status.HTTP_201_CREATED,
    response_model=QaPairOut,
)
async def create_qa_pair(collection_id: uuid.UUID, body: QaPairCreate, user: UserDep, service: ServiceDep) -> QaPairOut:
    try:
        return await service.create(collection_id, user, body)
    except CollectionNotFoundError as error:
        raise _not_found(error) from error
    except TooManyDocumentsError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Only a golden pair can have several relevant documents"
        ) from error
    except UnknownDocumentError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A relevant document is not in this collection"
        ) from error


@router.delete(
    "/collections/{collection_id}/qa-pairs/{qa_pair_id}",
    summary="Remove a question/answer pair (and, for a generated one, its embedding)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_qa_pair(
    collection_id: uuid.UUID, qa_pair_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> Response:
    try:
        await service.delete(collection_id, user, qa_pair_id)
    except (CollectionNotFoundError, QaPairNotFoundError) as error:
        raise _not_found(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/collections/{collection_id}/qa-pairs/{qa_pair_id}",
    summary="Validate or unvalidate a generated pair (a golden pair is always validated)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_qa_pair_validation(
    collection_id: uuid.UUID,
    qa_pair_id: uuid.UUID,
    body: QaPairValidationUpdate,
    user: UserDep,
    service: ServiceDep,
) -> Response:
    try:
        await service.set_validated(collection_id, user, qa_pair_id, body.validated)
    except (CollectionNotFoundError, QaPairNotFoundError) as error:
        raise _not_found(error) from error
    except GoldenPairNotValidatableError as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "golden_always_validated", "message": "Une question de test est toujours validée."},
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
