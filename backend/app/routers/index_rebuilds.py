import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.index_rebuild import (
    IndexRebuildOut,
    RebuildFailureIn,
    RebuildPlanOut,
    RebuildVectorsIn,
)
from app.services.collection_service import CollectionNotFoundError
from app.services.index_rebuild_service import (
    IndexRebuildService,
    RebuildInProgressError,
    RebuildNotFoundError,
    RebuildStateError,
)

# Blue/green rebuild of a collection's search index (#12): the owner starts it, follows it, then
# validates or rolls back the switch (`router`); the job in worker/document_process drives the build
# (`internal_router`).
router = APIRouter(tags=["Documents"])
internal_router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


def get_index_rebuild_service(db: Annotated[AsyncSession, Depends(get_db)]) -> IndexRebuildService:
    return IndexRebuildService(db)


ServiceDep = Annotated[IndexRebuildService, Depends(get_index_rebuild_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _error(error: Exception) -> HTTPException:
    if isinstance(error, CollectionNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    if isinstance(error, RebuildNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Index rebuild not found")
    if isinstance(error, RebuildInProgressError):
        return HTTPException(status.HTTP_409_CONFLICT, "An index rebuild is already in progress for this collection")
    return HTTPException(status.HTTP_409_CONFLICT, "The index rebuild is not in a state that allows this")


@router.post(
    "/collections/{collection_id}/documents/reindex",
    summary="Rebuild the collection's search index with its configured embedding model, without interrupting "
    "search: the current index keeps answering until the new one is complete and swapped in",
    response_model=IndexRebuildOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_rebuild(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> IndexRebuildOut:
    try:
        return await service.start(collection_id, user)
    except (CollectionNotFoundError, RebuildInProgressError) as error:
        raise _error(error) from error


@router.get(
    "/collections/{collection_id}/index-rebuild",
    summary="The collection's latest index rebuild (null when it never had one)",
    response_model=IndexRebuildOut | None,
)
async def get_latest_rebuild(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> IndexRebuildOut | None:
    try:
        return await service.latest(collection_id, user)
    except CollectionNotFoundError as error:
        raise _error(error) from error


@router.post(
    "/collections/{collection_id}/index-rebuild/{rebuild_id}/finalize",
    summary="Validate a rebuild that has been swapped in: the old index, kept for a rollback, is deleted",
    response_model=IndexRebuildOut,
)
async def finalize_rebuild(
    collection_id: uuid.UUID, rebuild_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> IndexRebuildOut:
    try:
        return await service.finalize(collection_id, user, rebuild_id)
    except (CollectionNotFoundError, RebuildNotFoundError, RebuildStateError) as error:
        raise _error(error) from error


@router.post(
    "/collections/{collection_id}/index-rebuild/{rebuild_id}/rollback",
    summary="Go back to the old index, kept since the swap, and its embedding model",
    response_model=IndexRebuildOut,
)
async def rollback_rebuild(
    collection_id: uuid.UUID, rebuild_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> IndexRebuildOut:
    try:
        return await service.rollback(collection_id, user, rebuild_id)
    except (CollectionNotFoundError, RebuildNotFoundError, RebuildStateError) as error:
        raise _error(error) from error


@internal_router.get(
    "/index-rebuilds/{rebuild_id}/plan",
    summary="What the index being built still lacks (the next points to embed), and the rebuild's state",
    response_model=RebuildPlanOut,
)
async def get_plan(rebuild_id: uuid.UUID, service: ServiceDep) -> RebuildPlanOut:
    try:
        return await service.plan(rebuild_id)
    except RebuildNotFoundError as error:
        raise _error(error) from error


@internal_router.post(
    "/index-rebuilds/{rebuild_id}/vectors",
    summary="Store the vectors the worker made; one made from a text that changed since the plan is dropped",
)
async def submit_vectors(rebuild_id: uuid.UUID, body: RebuildVectorsIn, service: ServiceDep) -> dict[str, int]:
    try:
        return {"stored": await service.submit(rebuild_id, body.model, body.points)}
    except (RebuildNotFoundError, RebuildStateError) as error:
        raise _error(error) from error


@internal_router.post(
    "/index-rebuilds/{rebuild_id}/swap",
    summary="Swap the new index in, atomically, once it holds everything (false while a plan still has work)",
)
async def swap(rebuild_id: uuid.UUID, service: ServiceDep) -> dict[str, bool]:
    try:
        return {"swapped": await service.swap(rebuild_id)}
    except RebuildNotFoundError as error:
        raise _error(error) from error


@internal_router.post(
    "/index-rebuilds/{rebuild_id}/fail",
    summary="The build gave up: the active index is untouched, the half-built one is removed",
)
async def fail(rebuild_id: uuid.UUID, body: RebuildFailureIn, service: ServiceDep) -> dict[str, str]:
    try:
        await service.fail(rebuild_id, body.error)
    except RebuildNotFoundError as error:
        raise _error(error) from error
    return {"status": "ok"}
