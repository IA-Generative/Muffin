from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.cgu import CguStatusOut
from app.services.cgu_service import CguService

router = APIRouter(prefix="/cgu", tags=["Cgu"])


def get_cgu_service(db: Annotated[AsyncSession, Depends(get_db)]) -> CguService:
    return CguService(db)


ServiceDep = Annotated[CguService, Depends(get_cgu_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/status",
    summary="The active CGU version's content and whether the current user has accepted it - "
    "used to gate the app until they do (§127)",
)
async def get_cgu_status(user: UserDep, service: ServiceDep) -> CguStatusOut:
    status_ = await service.get_status(user)
    return CguStatusOut(
        version=status_.version, content=status_.content, accepted=status_.accepted, is_update=status_.is_update
    )


@router.post("/accept", summary="Accept the currently active CGU version, for the current user")
async def accept_cgu(user: UserDep, service: ServiceDep) -> CguStatusOut:
    status_ = await service.accept(user)
    return CguStatusOut(
        version=status_.version, content=status_.content, accepted=status_.accepted, is_update=status_.is_update
    )
