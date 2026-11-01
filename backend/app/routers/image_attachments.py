import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.image_attachment import AttachmentOut, AttachmentStatusOut
from app.services.image_attachment_service import AttachmentError, ImageAttachmentService, _settings

router = APIRouter(tags=["Images"])


def get_attachment_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ImageAttachmentService:
    return ImageAttachmentService(db)


ServiceDep = Annotated[ImageAttachmentService, Depends(get_attachment_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def refused(error: AttachmentError) -> HTTPException:
    """The API's error: the status, and a code that does not change with words for the person."""
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


@router.get(
    "/images/attachments/status",
    summary="Whether images can be attached to a message (#512): only when a model of the hub reads them",
    response_model=AttachmentStatusOut,
)
async def get_status(user: UserDep, service: ServiceDep) -> AttachmentStatusOut:
    return await service.status()


@router.post(
    "/images/attachments",
    summary="Keep an image chosen in the composer until the message that carries it is sent. Only PNG, JPEG or WebP, "
    "checked on their bytes; refused when no model reads images",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def stage_image(file: UploadFile, user: UserDep, service: ServiceDep) -> AttachmentOut:
    # One byte more than the limit is read: enough to tell that it is too heavy, never the whole of a huge upload.
    data = await file.read(_settings.IMAGES_ATTACH_MAX_BYTES + 1)
    try:
        return await service.stage(user, data)
    except AttachmentError as error:
        raise refused(error) from error


@router.get(
    "/images/attachments/{image_id}",
    summary="An image chosen in the composer and not sent yet, for its owner only",
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}},
)
async def read_staged_image(image_id: uuid.UUID, user: UserDep, service: ServiceDep) -> Response:
    try:
        content, content_type = await service.read(user, image_id)
    except AttachmentError as error:
        raise refused(error) from error
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"},
    )


@router.delete(
    "/images/attachments/{image_id}",
    summary="Remove an image chosen in the composer and not sent yet",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def discard_staged_image(image_id: uuid.UUID, user: UserDep, service: ServiceDep) -> Response:
    try:
        await service.discard(user, image_id)
    except AttachmentError as error:
        raise refused(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
