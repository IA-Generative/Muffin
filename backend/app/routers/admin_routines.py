import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.repositories.routine_repository import RoutineRepository
from app.schemas.pagination import Page, PaginationParams
from app.schemas.routine import AdminRoutineOut, RoutineSettingsOut, RoutineSettingsUpdate, ScheduleOut
from app.services.routine_service import RoutineAdminService, RoutineNotFoundError

router = APIRouter(prefix="/admin/routines", tags=["Admin"])


def get_admin_user(user: Annotated[RequestContext, Depends(get_current_user)]) -> RequestContext:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


AdminDep = Annotated[RequestContext, Depends(get_admin_user)]


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RoutineAdminService:
    return RoutineAdminService(db)


ServiceDep = Annotated[RoutineAdminService, Depends(get_service)]
PaginationDep = Annotated[PaginationParams, Depends()]


@router.get("/settings", summary="The limits of the routines for the whole application")
async def get_settings(_user: AdminDep, service: ServiceDep) -> RoutineSettingsOut:
    return RoutineSettingsOut.model_validate(await service.settings(), from_attributes=True)


@router.patch("/settings", summary="Changes the limits of the routines, or turns the function on or off")
async def update_settings(body: RoutineSettingsUpdate, _user: AdminDep, service: ServiceDep) -> RoutineSettingsOut:
    changes = body.model_dump(exclude_none=True)
    return RoutineSettingsOut.model_validate(await service.update_settings(changes), from_attributes=True)


@router.get("", summary="Every routine: whose, how often, and what it costs - not what it asks nor what it answers")
async def list_routines(_user: AdminDep, service: ServiceDep, pagination: PaginationDep) -> Page[AdminRoutineOut]:
    rows, total = await service.everyone(pagination)
    since = datetime.now(UTC) - timedelta(days=30)
    tokens = await RoutineRepository(service.db).tokens_by_routine([routine.id for routine, _last in rows], since)
    items = [
        AdminRoutineOut(
            id=routine.id,
            name=routine.name,
            owner_display=routine.owner_display,
            schedule=ScheduleOut(
                kind=routine.kind,
                timezone=routine.timezone,
                interval_minutes=routine.interval_minutes,
                time_of_day=routine.time_of_day,
                weekdays=list(routine.weekdays) if routine.weekdays else None,
                day_of_month=routine.day_of_month,
            ),
            state=routine.state,
            suspended_reason=routine.suspended_reason,
            next_run_at=routine.next_run_at,
            last_run_at=routine.last_run_at,
            consecutive_failures=routine.consecutive_failures,
            last_status=last.status if last else None,
            tokens_30_days=tokens.get(routine.id, 0),
            created_at=routine.created_at,
        )
        for routine, last in rows
    ]
    return pagination.to_page(items, total)


@router.post("/{routine_id}/suspend", status_code=status.HTTP_204_NO_CONTENT, summary="Puts a routine aside")
async def suspend_routine(routine_id: uuid.UUID, _user: AdminDep, service: ServiceDep) -> None:
    try:
        await service.suspend(routine_id)
    except RoutineNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found") from error


@router.post(
    "/{routine_id}/release",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lifts an administrator's suspension: the routine is paused, its owner resumes it",
)
async def release_routine(routine_id: uuid.UUID, _user: AdminDep, service: ServiceDep) -> None:
    try:
        await service.release(routine_id)
    except RoutineNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found") from error
