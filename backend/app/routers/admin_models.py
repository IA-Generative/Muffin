from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.model_profiles import (
    ClassifierModelUpdate,
    ModelProfileOut,
    ModelProfilesOut,
    ModelProfileUpdate,
)
from app.services.model_catalog_service import ModelCatalogService, NotAdminError, UnknownModelError

router = APIRouter(prefix="/admin/models", tags=["Admin"])


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ModelCatalogService:
    return ModelCatalogService(db)


ServiceDep = Annotated[ModelCatalogService, Depends(get_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]

_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.get(
    "",
    summary="The models of the hub, with what they can do and how an administrator rated them",
    response_model=ModelProfilesOut,
)
async def list_models(user: UserDep, service: ServiceDep) -> ModelProfilesOut:
    try:
        return await service.list_profiles(user)
    except NotAdminError as error:
        raise _FORBIDDEN from error


@router.put(
    "/classifier",
    summary="Choose the model that classifies the requests in auto mode (null: the cheapest one)",
    response_model=ClassifierModelUpdate,
)
async def set_classifier(update: ClassifierModelUpdate, user: UserDep, service: ServiceDep) -> ClassifierModelUpdate:
    try:
        return ClassifierModelUpdate(classifier_model=await service.set_classifier_model(user, update.classifier_model))
    except NotAdminError as error:
        raise _FORBIDDEN from error
    except UnknownModelError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat model not found") from error


@router.put(
    "/{model_id:path}",
    summary="Rate a model: its score from 0 to 100, what it does well, and whether auto mode may pick it",
    response_model=ModelProfileOut,
)
async def update_model(
    model_id: str, update: ModelProfileUpdate, user: UserDep, service: ServiceDep
) -> ModelProfileOut:
    try:
        return await service.update_profile(user, model_id, update)
    except NotAdminError as error:
        raise _FORBIDDEN from error
    except UnknownModelError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found") from error
