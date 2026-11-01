import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.memory import (
    HabitsOut,
    MemoryExportOut,
    MemoryItemCreate,
    MemoryItemOut,
    MemoryItemUpdate,
    MemoryOut,
    MemorySettingsUpdate,
    MemoryStatsOut,
)
from app.services.memory_service import MemoryItemNotFoundError, MemoryRequestError, MemoryService

router = APIRouter(tags=["Memory"])

UserDep = Annotated[RequestContext, Depends(get_current_user)]


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> MemoryService:
    return MemoryService(db)


ServiceDep = Annotated[MemoryService, Depends(get_service)]


def _refused(error: MemoryRequestError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory item not found")


@router.get("/memory", summary="What the assistant remembers of me (#283)")
async def get_memory(user: UserDep, service: ServiceDep) -> MemoryOut:
    return await service.overview(user)


@router.get("/memory/habits", summary="The collections I use most, to propose first (#286)")
async def get_habits(user: UserDep, service: ServiceDep) -> HabitsOut:
    return await service.habits(user)


@router.get("/memory/export", summary="Everything remembered of me, as JSON")
async def export_memory(user: UserDep, service: ServiceDep) -> MemoryExportOut:
    return await service.export(user)


@router.put("/memory/settings", summary="Turn my memory on or off")
async def set_memory_enabled(body: MemorySettingsUpdate, user: UserDep, service: ServiceDep) -> MemoryOut:
    await service.set_enabled(user, body.enabled)
    return await service.overview(user)


@router.post("/memory/items", status_code=status.HTTP_201_CREATED, summary="Ask the assistant to remember something")
async def add_item(body: MemoryItemCreate, user: UserDep, service: ServiceDep, response: Response) -> MemoryItemOut:
    try:
        item, created = await service.add(user, body.kind, body.value)
    except MemoryRequestError as error:
        raise _refused(error) from error
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return MemoryItemOut.model_validate(item)


@router.patch("/memory/items/{item_id}", summary="Correct, turn off or on one item")
async def update_item(item_id: uuid.UUID, body: MemoryItemUpdate, user: UserDep, service: ServiceDep) -> MemoryItemOut:
    try:
        return MemoryItemOut.model_validate(await service.update(user, item_id, body.value, body.enabled))
    except MemoryItemNotFoundError as error:
        raise _not_found() from error
    except MemoryRequestError as error:
        raise _refused(error) from error


@router.delete("/memory/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Forget one item")
async def delete_item(item_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete(user, item_id)
    except MemoryItemNotFoundError as error:
        raise _not_found() from error


@router.delete("/memory/items", status_code=status.HTTP_204_NO_CONTENT, summary="Forget everything")
async def delete_all(user: UserDep, service: ServiceDep) -> None:
    await service.delete_all(user)


@router.get("/admin/memory/stats", summary="How many people use the memory - counts only, never what it holds")
async def memory_stats(user: UserDep, service: ServiceDep) -> MemoryStatsOut:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return await service.stats()
