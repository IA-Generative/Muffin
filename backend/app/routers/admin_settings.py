from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.app_settings import AppSettingsOut, AppSettingsUpdate
from app.services.app_settings_service import AppSettingsService, NotAdminError

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_app_settings_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AppSettingsService:
    return AppSettingsService(db)


ServiceDep = Annotated[AppSettingsService, Depends(get_app_settings_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get("/settings", summary="Get the global admin-only settings", response_model=AppSettingsOut)
async def get_admin_settings(user: UserDep, service: ServiceDep) -> AppSettingsOut:
    try:
        return await service.get_settings(user)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error


@router.patch(
    "/settings/embedding-model",
    summary="Set the global embedding model used to match a query against every collection's description",
    response_model=AppSettingsOut,
)
async def update_embedding_model(update: AppSettingsUpdate, user: UserDep, service: ServiceDep) -> AppSettingsOut:
    try:
        return await service.update_embedding_model(user, update)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
