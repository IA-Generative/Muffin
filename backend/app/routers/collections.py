import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.collection import CollectionOut, CollectionUpdate
from app.schemas.pagination import Page, PaginationParams
from app.services.collection_service import CollectionNotFoundError, CollectionService

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


@router.delete("/collections/{collection_id}", summary="Delete a collection", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
