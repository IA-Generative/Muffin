from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.cgu import CguVersionCreate, CguVersionOut
from app.services.cgu_service import CguService, CguVersionNotFoundError, NotAdminError

router = APIRouter(prefix="/admin/cgu", tags=["Admin"])


def get_cgu_service(db: Annotated[AsyncSession, Depends(get_db)]) -> CguService:
    return CguService(db)


ServiceDep = Annotated[CguService, Depends(get_cgu_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get("/versions", summary="List every CGU version, newest first")
async def list_cgu_versions(user: UserDep, service: ServiceDep) -> list[CguVersionOut]:
    try:
        versions = await service.list_versions(user)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return [CguVersionOut.model_validate(version) for version in versions]


@router.post("/versions", summary="Create a new (inactive) CGU version")
async def create_cgu_version(update: CguVersionCreate, user: UserDep, service: ServiceDep) -> CguVersionOut:
    try:
        version = await service.create_version(user, update.content)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return CguVersionOut.model_validate(version)


@router.post(
    "/versions/{version}/activate",
    summary="Activate a CGU version (publishing a new one, or rolling back to an older one) - "
    "every user who already accepted a different version will be asked to accept this one",
)
async def activate_cgu_version(version: int, user: UserDep, service: ServiceDep) -> CguVersionOut:
    try:
        activated = await service.activate(user, version)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    except CguVersionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return CguVersionOut.model_validate(activated)
