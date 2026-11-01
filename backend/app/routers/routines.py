import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.pagination import Page, PaginationParams
from app.schemas.routine import (
    PreviewOut,
    RoutineCreate,
    RoutineOut,
    RoutineRunOut,
    RoutineStatusOut,
    RoutineUpdate,
    ScheduleIn,
    TriggerOut,
)
from app.services.routine_service import RoutineError, RoutineNotFoundError, RoutineService

router = APIRouter(prefix="/routines", tags=["Routines"])

UserDep = Annotated[RequestContext, Depends(get_current_user)]


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RoutineService:
    return RoutineService(db)


ServiceDep = Annotated[RoutineService, Depends(get_service)]
PaginationDep = Annotated[PaginationParams, Depends()]


def _refused(error: RoutineError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")


@router.get("/status", summary="Whether routines are on, and the limits the person is held to")
async def routines_status(user: UserDep, service: ServiceDep) -> RoutineStatusOut:
    return await service.status(user)


@router.post("/preview", summary="The next dates of a rhythm, to check it before keeping it")
async def preview(body: ScheduleIn, user: UserDep, service: ServiceDep) -> PreviewOut:
    try:
        return await service.preview(user, body)
    except RoutineError as error:
        raise _refused(error) from error


@router.get("", summary="The person's own routines, with their last run")
async def list_routines(user: UserDep, service: ServiceDep) -> list[RoutineOut]:
    return await service.mine(user)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Makes a routine")
async def create_routine(body: RoutineCreate, user: UserDep, service: ServiceDep) -> RoutineOut:
    try:
        return await service.create(user, body)
    except RoutineError as error:
        raise _refused(error) from error


@router.get("/{routine_id}", summary="One of the person's routines")
async def get_routine(routine_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RoutineOut:
    try:
        return await service.get(user, routine_id)
    except RoutineNotFoundError as error:
        raise _not_found() from error


@router.patch("/{routine_id}", summary="Changes a routine")
async def update_routine(routine_id: uuid.UUID, body: RoutineUpdate, user: UserDep, service: ServiceDep) -> RoutineOut:
    try:
        return await service.update(user, routine_id, body)
    except RoutineNotFoundError as error:
        raise _not_found() from error
    except RoutineError as error:
        raise _refused(error) from error


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deletes a routine and its history")
async def delete_routine(routine_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete(user, routine_id)
    except RoutineNotFoundError as error:
        raise _not_found() from error


@router.post("/{routine_id}/pause", summary="Pauses a routine")
async def pause_routine(routine_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RoutineOut:
    try:
        return await service.pause(user, routine_id)
    except RoutineNotFoundError as error:
        raise _not_found() from error


@router.post("/{routine_id}/resume", summary="Resumes a routine that is paused or was suspended by the system")
async def resume_routine(routine_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RoutineOut:
    try:
        return await service.resume(user, routine_id)
    except RoutineNotFoundError as error:
        raise _not_found() from error
    except RoutineError as error:
        raise _refused(error) from error


@router.post("/{routine_id}/run", summary="Runs a routine now, to try it without waiting for its date")
async def run_routine(routine_id: uuid.UUID, user: UserDep, service: ServiceDep) -> TriggerOut:
    try:
        return TriggerOut(run=await service.run_now(user, routine_id))
    except RoutineNotFoundError as error:
        raise _not_found() from error
    except RoutineError as error:
        raise _refused(error) from error


@router.get("/{routine_id}/runs", summary="The history of a routine: its runs, and why a run was not made")
async def routine_runs(
    routine_id: uuid.UUID, user: UserDep, service: ServiceDep, pagination: PaginationDep
) -> Page[RoutineRunOut]:
    try:
        return await service.runs(user, routine_id, pagination)
    except RoutineNotFoundError as error:
        raise _not_found() from error
