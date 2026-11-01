from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.image_generation import (
    ImageGenerationIn,
    ImageGenerationOut,
    ImageSettingsOut,
    ImageSettingsUpdate,
    ImageStatusOut,
    ImageTestOut,
)
from app.services.app_settings_service import NotAdminError
from app.services.image_generation_service import (
    ConversationNotFoundError,
    ImageGenerationError,
    ImageGenerationService,
)

router = APIRouter(tags=["Images"])


def get_image_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ImageGenerationService:
    return ImageGenerationService(db)


ServiceDep = Annotated[ImageGenerationService, Depends(get_image_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _refused(error: ImageGenerationError) -> HTTPException:
    """The API's error: the status, and a code that does not change with words for the person."""
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


def _not_admin() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.get(
    "/images/status",
    summary="Whether the generation of images is offered to the caller (on, ready, and theirs), and what is left of "
    "their day",
    response_model=ImageStatusOut,
)
async def get_status(user: UserDep, service: ServiceDep) -> ImageStatusOut:
    return await service.status(user)


@router.post(
    "/images/generations",
    summary="Generate an image from a description and put it in a conversation (a new one when none is given). 404 "
    "when the function is off; no call is made to the provider before the caller is allowed and within their quota",
    response_model=ImageGenerationOut,
)
async def generate_image(body: ImageGenerationIn, user: UserDep, service: ServiceDep) -> ImageGenerationOut:
    try:
        return await service.generate(user, body.prompt, body.conversation_id, body.image_ids)
    except ImageGenerationError as error:
        raise _refused(error) from error
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.get(
    "/admin/image-generation",
    summary="The settings of the generation of images (never the key)",
    response_model=ImageSettingsOut,
)
async def get_settings(user: UserDep, service: ServiceDep) -> ImageSettingsOut:
    try:
        return await service.get_settings(user)
    except NotAdminError as error:
        raise _not_admin() from error


@router.patch(
    "/admin/image-generation",
    summary="Change the settings of the generation of images; the key is only ever written",
    response_model=ImageSettingsOut,
)
async def update_settings(body: ImageSettingsUpdate, user: UserDep, service: ServiceDep) -> ImageSettingsOut:
    try:
        return await service.update_settings(user, body)
    except NotAdminError as error:
        raise _not_admin() from error
    except ImageGenerationError as error:
        raise _refused(error) from error


@router.post(
    "/admin/image-generation/test",
    summary="Make a small image with the settings as they are: how long it took, or what went wrong. Not kept, not "
    "counted against a quota",
    response_model=ImageTestOut,
)
async def test_settings(user: UserDep, service: ServiceDep) -> ImageTestOut:
    try:
        return await service.test(user)
    except NotAdminError as error:
        raise _not_admin() from error
