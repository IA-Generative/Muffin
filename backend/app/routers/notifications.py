import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.notification import (
    MarkReadIn,
    NotificationPage,
    PreferenceOut,
    PreferencesIn,
    UnreadCountOut,
)
from app.services.notification_service import (
    InvalidCursorError,
    NotificationNotFoundError,
    NotificationService,
    UnknownNotificationTypeError,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])

UserDep = Annotated[RequestContext, Depends(get_current_user)]


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> NotificationService:
    return NotificationService(db)


ServiceDep = Annotated[NotificationService, Depends(get_service)]


@router.get("", summary="The person's own notifications, newest first (by cursor)")
async def list_notifications(
    user: UserDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    unread_only: bool = False,
) -> NotificationPage:
    try:
        return await service.page(user, limit, cursor, unread_only)
    except InvalidCursorError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid cursor") from error


@router.get("/unread-count", summary="How many are not read: what the bell shows")
async def unread_count(user: UserDep, service: ServiceDep) -> UnreadCountOut:
    return UnreadCountOut(count=await service.unread_count(user))


@router.post("/read", summary="Marks some notifications read, or all of them when no id is given")
async def mark_read(body: MarkReadIn, user: UserDep, service: ServiceDep) -> UnreadCountOut:
    await service.mark_read(user, body.ids)
    return UnreadCountOut(count=await service.unread_count(user))


@router.get("/preferences", summary="What the person wants to be told of, by type")
async def preferences(user: UserDep, service: ServiceDep) -> list[PreferenceOut]:
    return await service.preferences(user)


@router.put("/preferences", summary="Changes what the person wants to be told of")
async def set_preferences(body: PreferencesIn, user: UserDep, service: ServiceDep) -> list[PreferenceOut]:
    try:
        return await service.set_preferences(user, {item.type: item.app for item in body.preferences})
    except UnknownNotificationTypeError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown type") from error


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deletes one notification")
async def delete_notification(notification_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete(user, notification_id)
    except NotificationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found") from error
