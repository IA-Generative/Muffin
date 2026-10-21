from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.usage import UsageOut
from app.services.usage_service import NotAdminError, UsageService

router = APIRouter(tags=["Usage"])


def get_usage_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UsageService:
    return UsageService(db)


ServiceDep = Annotated[UsageService, Depends(get_usage_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]
DaysQuery = Annotated[int, Query(ge=1, le=365)]


@router.get(
    "/usage/me",
    summary="Tokens my questions and my documents consumed, in total and per step, day and model",
    response_model=UsageOut,
)
async def my_usage(user: UserDep, service: ServiceDep, days: DaysQuery = 30) -> UsageOut:
    return await service.mine(user, days)


@router.get(
    "/admin/usage",
    summary="Everyone's token consumption, or one user's (user_id), with the per-user breakdown",
    response_model=UsageOut,
)
async def overall_usage(
    user: UserDep, service: ServiceDep, days: DaysQuery = 30, user_id: str | None = None
) -> UsageOut:
    try:
        return await service.overall(user, days, user_id)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
