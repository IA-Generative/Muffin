import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.guardrail import (
    AuditOut,
    GuardrailCreate,
    GuardrailOut,
    GuardrailStatsOut,
    GuardrailUpdate,
    PolicyOut,
    PolicyUpdate,
    ProbeIn,
    ProbeOut,
    ReorderIn,
)
from app.schemas.pagination import Page, PaginationParams
from app.services.guardrail_service import GuardrailError, GuardrailNotFoundError, GuardrailService

router = APIRouter(prefix="/admin/guardrails", tags=["Admin"])


def get_admin_user(user: Annotated[RequestContext, Depends(get_current_user)]) -> RequestContext:
    """The guardrails are defined by an administrator and no one else: what they hold - patterns, prompts, addresses -
    is what a person would need to get round them, so it is not shown to anyone else."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


AdminDep = Annotated[RequestContext, Depends(get_admin_user)]


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> GuardrailService:
    return GuardrailService(db)


ServiceDep = Annotated[GuardrailService, Depends(get_service)]
PaginationDep = Annotated[PaginationParams, Depends()]


def _refused(error: GuardrailError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message})


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guardrail not found")


@router.get(
    "", summary="Every guardrail, in the order they run (the ones that come with the application are made once)"
)
async def list_guardrails(_user: AdminDep, service: ServiceDep) -> list[GuardrailOut]:
    return await service.all()


@router.post("", status_code=status.HTTP_201_CREATED, summary="Makes a guardrail")
async def create_guardrail(body: GuardrailCreate, user: AdminDep, service: ServiceDep) -> GuardrailOut:
    try:
        return await service.create(user, body)
    except GuardrailError as error:
        raise _refused(error) from error


@router.get("/policy", summary="How the guardrails as a whole decide")
async def get_policy(_user: AdminDep, service: ServiceDep) -> PolicyOut:
    return await service.policy()


@router.patch("/policy", summary="Changes how the guardrails as a whole decide")
async def update_policy(body: PolicyUpdate, user: AdminDep, service: ServiceDep) -> PolicyOut:
    return await service.update_policy(user, body)


@router.post("/reorder", summary="Sets the order of the guardrails, inside their stage")
async def reorder_guardrails(body: ReorderIn, user: AdminDep, service: ServiceDep) -> list[GuardrailOut]:
    try:
        return await service.reorder(user, body.ids)
    except GuardrailError as error:
        raise _refused(error) from error


@router.post("/test", summary="What each guardrail says of a text, without making a run and without keeping the text")
async def probe(body: ProbeIn, user: AdminDep, service: ServiceDep) -> ProbeOut:
    return await service.probe(user, body.text, body.guardrail_ids)


@router.get("/audit", summary="Who changed the guardrails, when, and what they were before and after")
async def audit(
    _user: AdminDep,
    service: ServiceDep,
    pagination: PaginationDep,
    guardrail_id: uuid.UUID | None = None,
) -> Page[AuditOut]:
    rows, total = await service.audit(pagination.limit, pagination.offset, guardrail_id)
    return pagination.to_page(rows, total)


@router.get("/stats", summary="What the guardrails did, by guardrail and by day: counts and times, never any text")
async def stats(
    _user: AdminDep, service: ServiceDep, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> GuardrailStatsOut:
    return await service.stats(days)


@router.get("/{guardrail_id}", summary="One guardrail")
async def get_guardrail(guardrail_id: uuid.UUID, _user: AdminDep, service: ServiceDep) -> GuardrailOut:
    try:
        return await service.get(guardrail_id)
    except GuardrailNotFoundError as error:
        raise _not_found() from error


@router.patch("/{guardrail_id}", summary="Changes a guardrail, turns it on or off")
async def update_guardrail(
    guardrail_id: uuid.UUID, body: GuardrailUpdate, user: AdminDep, service: ServiceDep
) -> GuardrailOut:
    try:
        return await service.update(user, guardrail_id, body)
    except GuardrailNotFoundError as error:
        raise _not_found() from error
    except GuardrailError as error:
        raise _refused(error) from error


@router.delete("/{guardrail_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deletes a guardrail")
async def delete_guardrail(guardrail_id: uuid.UUID, user: AdminDep, service: ServiceDep) -> None:
    try:
        await service.delete(user, guardrail_id)
    except GuardrailNotFoundError as error:
        raise _not_found() from error
