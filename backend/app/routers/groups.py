import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import SharingNotConfiguredError
from app.db import get_db
from app.schemas.group import GroupCreate, GroupOut, GroupUpdate, MemberAdd, MemberOut
from app.services.group_service import (
    AlreadyMemberError,
    GroupNotFoundError,
    GroupNotManageableError,
    GroupReadOnlyError,
    GroupService,
    MemberNotFoundError,
)

router = APIRouter(prefix="/groups", tags=["Groups"])


def get_group_service(db: Annotated[AsyncSession, Depends(get_db)]) -> GroupService:
    return GroupService(db)


ServiceDep = Annotated[GroupService, Depends(get_group_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, GroupNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if isinstance(error, MemberNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if isinstance(error, GroupNotManageableError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner of the group or an administrator can do this")
    if isinstance(error, GroupReadOnlyError):
        return HTTPException(status.HTTP_409_CONFLICT, "This group is copied from another system and is read only")
    if isinstance(error, AlreadyMemberError):
        return HTTPException(status.HTTP_409_CONFLICT, "Already in the group")
    if isinstance(error, SharingNotConfiguredError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sharing is not configured")
    raise error


@router.get("", summary="The groups the caller owns or is in (all of them for an administrator)")
async def list_groups(user: UserDep, service: ServiceDep) -> list[GroupOut]:
    return await service.list_groups(user)


@router.post("", summary="Make a group, owned by the caller", status_code=status.HTTP_201_CREATED)
async def create_group(data: GroupCreate, user: UserDep, service: ServiceDep) -> GroupOut:
    return await service.create_group(user, data)


@router.get("/{group_id}", summary="A group the caller owns or is in")
async def get_group(group_id: uuid.UUID, user: UserDep, service: ServiceDep) -> GroupOut:
    try:
        return await service.get_group(group_id, user)
    except GroupNotFoundError as error:
        raise _http_error(error) from error


@router.patch("/{group_id}", summary="Rename a group or change its description - its owner or an administrator")
async def update_group(group_id: uuid.UUID, data: GroupUpdate, user: UserDep, service: ServiceDep) -> GroupOut:
    try:
        return await service.update_group(group_id, user, data)
    except (GroupNotFoundError, GroupNotManageableError, GroupReadOnlyError) as error:
        raise _http_error(error) from error


@router.delete(
    "/{group_id}",
    summary="Delete a group, its members and the shares of collections that pointed to it",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group(group_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_group(group_id, user)
    except (GroupNotFoundError, GroupNotManageableError, GroupReadOnlyError) as error:
        raise _http_error(error) from error


@router.get("/{group_id}/members", summary="Who is in a group, with the invitations waiting - who manages it")
async def list_members(group_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[MemberOut]:
    try:
        return await service.list_members(group_id, user)
    except (GroupNotFoundError, GroupNotManageableError) as error:
        raise _http_error(error) from error


@router.post(
    "/{group_id}/members",
    summary="Add someone by email (an invitation that never confirms the address has an account) or by "
    "Keycloak subject",
    status_code=status.HTTP_201_CREATED,
)
async def add_member(group_id: uuid.UUID, data: MemberAdd, user: UserDep, service: ServiceDep) -> MemberOut:
    try:
        return await service.add_member(group_id, user, data)
    except (
        GroupNotFoundError,
        GroupNotManageableError,
        GroupReadOnlyError,
        AlreadyMemberError,
        SharingNotConfiguredError,
    ) as error:
        raise _http_error(error) from error


@router.delete("/{group_id}/members/{member_id}", summary="Take someone out", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: uuid.UUID, member_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.remove_member(group_id, user, member_id)
    except (GroupNotFoundError, GroupNotManageableError, GroupReadOnlyError, MemberNotFoundError) as error:
        raise _http_error(error) from error
