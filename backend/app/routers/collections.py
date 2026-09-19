import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import SharingNotConfiguredError
from app.db import get_db
from app.schemas.collection import (
    CollectionOut,
    CollectionSettingsUpdate,
    CollectionUpdate,
    EntityOut,
    GroundednessStatsOut,
    QaPairOut,
    RelationOut,
    ShareCreate,
    ShareOut,
    VisibilityUpdate,
)
from app.schemas.pagination import Page, PaginationParams
from app.services.collection_service import (
    AlreadyInvitedError,
    CollectionNotFoundError,
    CollectionService,
    ShareNotFoundError,
)

router = APIRouter(tags=["Collections"])


def get_collection_service(db: Annotated[AsyncSession, Depends(get_db)]) -> CollectionService:
    return CollectionService(db)


ServiceDep = Annotated[CollectionService, Depends(get_collection_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get("/collections", summary="List the current user's collections", response_model=Page[CollectionOut])
async def list_collections(
    user: UserDep, service: ServiceDep, pagination: Annotated[PaginationParams, Depends()]
) -> Page[CollectionOut]:
    return await service.list_collections(user, pagination)


@router.post(
    "/collections",
    summary="Create a new, empty collection",
    status_code=status.HTTP_201_CREATED,
    response_model=CollectionOut,
)
async def create_collection(user: UserDep, service: ServiceDep) -> CollectionOut:
    return await service.create_collection(user)


@router.get("/collections/{collection_id}", summary="Get a collection", response_model=CollectionOut)
async def get_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> CollectionOut:
    try:
        return await service.get_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.patch(
    "/collections/{collection_id}",
    summary="Update a collection's name, description and/or tags",
    response_model=CollectionOut,
)
async def update_collection(
    collection_id: uuid.UUID, update: CollectionUpdate, user: UserDep, service: ServiceDep
) -> CollectionOut:
    try:
        return await service.update_collection(collection_id, user, update)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.patch(
    "/collections/{collection_id}/settings",
    summary="Update chunking, embedding model, per-step generation models, and pipeline instructions",
    response_model=CollectionOut,
)
async def update_collection_settings(
    collection_id: uuid.UUID, update: CollectionSettingsUpdate, user: UserDep, service: ServiceDep
) -> CollectionOut:
    try:
        return await service.update_settings(collection_id, user, update)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/qa-pairs",
    summary="List a collection's question/answer pairs (generated and manual)",
    response_model=list[QaPairOut],
)
async def list_qa_pairs(
    collection_id: uuid.UUID, user: UserDep, service: ServiceDep, document_id: uuid.UUID | None = None
) -> list[QaPairOut]:
    try:
        return await service.list_qa_pairs(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/groundedness",
    summary="Aggregate this collection's grounding verdicts - proportion of runs whose answer "
    "cited it but wasn't fully supported by evidence, plus recent examples",
    response_model=GroundednessStatsOut,
)
async def get_groundedness_stats(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> GroundednessStatsOut:
    try:
        return await service.get_groundedness_stats(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/entities",
    summary="List a collection's extracted entities",
    response_model=list[EntityOut],
)
async def list_entities(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[EntityOut]:
    try:
        return await service.list_entities(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/relations",
    summary="List a collection's extracted relations between entities",
    response_model=list[RelationOut],
)
async def list_relations(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[RelationOut]:
    try:
        return await service.list_relations(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.delete("/collections/{collection_id}", summary="Delete a collection", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.patch(
    "/collections/{collection_id}/visibility",
    summary="Make a collection private (default) or public - owner only",
    response_model=CollectionOut,
)
async def update_visibility(
    collection_id: uuid.UUID, update: VisibilityUpdate, user: UserDep, service: ServiceDep
) -> CollectionOut:
    try:
        return await service.update_visibility(collection_id, user, update.visibility)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/collections/{collection_id}/shares",
    summary="Invite a user (by email) or a Keycloak group to a collection - owner only. Never "
    "confirms whether the identifier matches a real account/group: it's always created PENDING "
    "and resolved the next time a matching user logs in (see app/core/sharing.py).",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareOut,
)
async def create_share(collection_id: uuid.UUID, create: ShareCreate, user: UserDep, service: ServiceDep) -> ShareOut:
    try:
        return await service.create_share(collection_id, user, create)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except AlreadyInvitedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already invited") from error
    except SharingNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sharing is not configured"
        ) from error


@router.get(
    "/collections/{collection_id}/shares",
    summary="List a collection's pending and active shares - owner only",
    response_model=list[ShareOut],
)
async def list_shares(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[ShareOut]:
    try:
        return await service.list_shares(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.delete(
    "/collections/{collection_id}/shares/{share_id}",
    summary="Revoke a pending or active share - owner only",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_share(collection_id: uuid.UUID, share_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_share(collection_id, user, share_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except ShareNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found") from error
