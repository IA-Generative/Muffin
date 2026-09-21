from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.prompt import PromptSummaryOut, PromptVersionCreate, PromptVersionOut
from app.services.prompt_service import NotAdminError, PromptNotFoundError, PromptService

router = APIRouter(prefix="/admin/prompts", tags=["Admin"])


def get_prompt_service(db: Annotated[AsyncSession, Depends(get_db)]) -> PromptService:
    return PromptService(db)


ServiceDep = Annotated[PromptService, Depends(get_prompt_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get("", summary="List the agent's prompts with their currently active version")
async def list_prompts(user: UserDep, service: ServiceDep) -> list[PromptSummaryOut]:
    try:
        active = await service.list_summaries(user)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return [
        PromptSummaryOut(name=version.name, active_version=PromptVersionOut.model_validate(version))
        for version in active
    ]


@router.get("/{name}/versions", summary="List every version of one prompt, newest first")
async def list_prompt_versions(name: str, user: UserDep, service: ServiceDep) -> list[PromptVersionOut]:
    try:
        versions = await service.list_versions(user, name)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return [PromptVersionOut.model_validate(version) for version in versions]


@router.post("/{name}/versions", summary="Create a new (inactive) version of a prompt")
async def create_prompt_version(
    name: str, update: PromptVersionCreate, user: UserDep, service: ServiceDep
) -> PromptVersionOut:
    try:
        version = await service.create_version(user, name, update.content)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    return PromptVersionOut.model_validate(version)


@router.post(
    "/{name}/versions/{version}/activate",
    summary="Activate a prompt version (publishing a new one, or rolling back to an older one)",
)
async def activate_prompt_version(name: str, version: int, user: UserDep, service: ServiceDep) -> PromptVersionOut:
    try:
        activated = await service.activate(user, name, version)
    except NotAdminError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from error
    except PromptNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return PromptVersionOut.model_validate(activated)
