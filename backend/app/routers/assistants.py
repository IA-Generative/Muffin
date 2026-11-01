import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import SharingNotConfiguredError
from app.db import get_db
from app.schemas.assistant import AssistantCreate, AssistantOut, AssistantUpdate, AssistantVisibilityUpdate
from app.schemas.collection import ShareCreate, ShareOut, ShareUpdate
from app.services.assistant_service import AssistantService
from app.services.group_service import GroupNotFoundError

router = APIRouter(tags=["Assistants"])


def get_assistant_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AssistantService:
    return AssistantService(db)


ServiceDep = Annotated[AssistantService, Depends(get_assistant_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/assistants",
    summary="The assistants the caller may use: their own, those shared with them, and the public ones",
    response_model=list[AssistantOut],
)
async def list_assistants(user: UserDep, service: ServiceDep) -> list[AssistantOut]:
    return await service.list_assistants(user)


@router.post("/assistants", status_code=status.HTTP_201_CREATED, response_model=AssistantOut)
async def create_assistant(body: AssistantCreate, user: UserDep, service: ServiceDep) -> AssistantOut:
    return await service.create(user, body)


@router.get("/assistants/{assistant_id}", response_model=AssistantOut)
async def get_assistant(assistant_id: uuid.UUID, user: UserDep, service: ServiceDep) -> AssistantOut:
    return await service.get(assistant_id, user)


@router.patch(
    "/assistants/{assistant_id}",
    summary="Change an assistant - its author, or someone it is shared with for writing. Raises its version.",
    response_model=AssistantOut,
)
async def update_assistant(
    assistant_id: uuid.UUID, body: AssistantUpdate, user: UserDep, service: ServiceDep
) -> AssistantOut:
    return await service.update(assistant_id, user, body)


@router.delete("/assistants/{assistant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assistant(assistant_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    await service.delete(assistant_id, user)


@router.post(
    "/assistants/{assistant_id}/duplicate",
    summary="Make one's own private version of an assistant one may read",
    status_code=status.HTTP_201_CREATED,
    response_model=AssistantOut,
)
async def duplicate_assistant(assistant_id: uuid.UUID, user: UserDep, service: ServiceDep) -> AssistantOut:
    return await service.duplicate(assistant_id, user)


@router.put(
    "/assistants/{assistant_id}/visibility",
    summary="Make an assistant public in the organisation (when allowed) or private again",
    response_model=AssistantOut,
)
async def set_visibility(
    assistant_id: uuid.UUID, body: AssistantVisibilityUpdate, user: UserDep, service: ServiceDep
) -> AssistantOut:
    return await service.set_visibility(assistant_id, user, body.visibility)


@router.post(
    "/assistants/{assistant_id}/shares",
    summary="Share an assistant with a user (by email) or a group - its author only. Like a collection's, never "
    "confirms whether the identifier matches a real account: it waits for that person to log in.",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareOut,
)
async def create_share(assistant_id: uuid.UUID, create: ShareCreate, user: UserDep, service: ServiceDep) -> ShareOut:
    try:
        return await service.create_share(assistant_id, user, create)
    except GroupNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found") from error
    except SharingNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sharing is not configured"
        ) from error


@router.get("/assistants/{assistant_id}/shares", response_model=list[ShareOut])
async def list_shares(assistant_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[ShareOut]:
    return await service.list_shares(assistant_id, user)


@router.patch("/assistants/{assistant_id}/shares/{share_id}", response_model=ShareOut)
async def update_share(
    assistant_id: uuid.UUID, share_id: uuid.UUID, update: ShareUpdate, user: UserDep, service: ServiceDep
) -> ShareOut:
    return await service.update_share(assistant_id, user, share_id, update)


@router.delete("/assistants/{assistant_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(assistant_id: uuid.UUID, share_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    await service.delete_share(assistant_id, user, share_id)
