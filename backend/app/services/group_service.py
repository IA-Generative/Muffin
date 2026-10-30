import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.core.sharing import hash_identifier, mask_email, normalize_email
from app.models.group import Group, MemberStatus, ResourceSource
from app.repositories.group_repository import GroupRepository
from app.schemas.group import GroupCreate, GroupOut, GroupUpdate, MemberAdd, MemberOut


class GroupNotFoundError(Exception):
    """No such group - or one the caller has no part in, whose existence is not theirs to learn."""


class GroupNotManageableError(Exception):
    """The caller can see the group (they are in it) but only its owner or an administrator manages it."""


class GroupReadOnlyError(Exception):
    """A group copied from another system (#453) is changed by the synchronisation only."""


class MemberNotFoundError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


class GroupService:
    """The groups people make in Muffin to share collections with (#455). Anyone makes groups and owns them; the
    owner, or an administrator, renames them and manages who is in. Whoever is in a group sees it and can share
    a collection with it, and that is all."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.groups = GroupRepository(db)

    @staticmethod
    def _can_manage(group: Group, user: RequestContext) -> bool:
        """Owner or administrator - and never a copied group, which nobody owns and only the synchronisation edits."""
        return group.source == ResourceSource.MUFFIN and (user.is_admin or group.owner_id == user.user_id)

    def _present(self, group: Group, user: RequestContext, members: int, pending: int) -> GroupOut:
        manageable = self._can_manage(group, user)
        return GroupOut(
            id=group.id,
            name=group.name,
            description=group.description,
            source=group.source,
            is_owner=group.owner_id == user.user_id,
            can_manage=manageable,
            member_count=members,
            pending_count=pending if manageable else 0,
        )

    async def list_groups(self, user: RequestContext) -> list[GroupOut]:
        rows = await self.groups.list_visible(user.user_id, user.is_admin)
        return [self._present(group, user, members, pending) for group, members, pending in rows]

    async def create_group(self, user: RequestContext, data: GroupCreate) -> GroupOut:
        group = await self.groups.create(user.user_id, data.name.strip(), data.description.strip())
        await self.db.commit()
        return self._present(group, user, 0, 0)

    async def get_visible(self, group_id: uuid.UUID, user: RequestContext) -> Group:
        """The group, if the caller owns it, is in it, or is an administrator; otherwise it does not exist."""
        group = await self.groups.get(group_id)
        if group is None:
            raise GroupNotFoundError(str(group_id))
        if not (user.is_admin or group.owner_id == user.user_id or await self.groups.is_member(group_id, user.user_id)):
            raise GroupNotFoundError(str(group_id))
        return group

    async def _get_manageable(self, group_id: uuid.UUID, user: RequestContext) -> Group:
        group = await self.get_visible(group_id, user)
        if group.source != ResourceSource.MUFFIN:
            raise GroupReadOnlyError(str(group_id))
        if not self._can_manage(group, user):
            raise GroupNotManageableError(str(group_id))
        return group

    async def get_group(self, group_id: uuid.UUID, user: RequestContext) -> GroupOut:
        group = await self.get_visible(group_id, user)
        members = await self.groups.list_members(group_id)
        active = sum(member.status == MemberStatus.ACTIVE for member, _ in members)
        return self._present(group, user, active, len(members) - active)

    async def update_group(self, group_id: uuid.UUID, user: RequestContext, data: GroupUpdate) -> GroupOut:
        group = await self._get_manageable(group_id, user)
        if data.name is not None:
            group.name = data.name.strip()
        if data.description is not None:
            group.description = data.description.strip()
        await self.db.commit()
        return await self.get_group(group_id, user)

    async def delete_group(self, group_id: uuid.UUID, user: RequestContext) -> None:
        group = await self._get_manageable(group_id, user)
        await self.groups.delete(group)
        await self.db.commit()

    async def list_members(self, group_id: uuid.UUID, user: RequestContext) -> list[MemberOut]:
        """Who is in the group - for whoever manages it. The others only know how many they are."""
        group = await self.get_visible(group_id, user)
        if not self._can_manage(group, user):
            raise GroupNotManageableError(str(group_id))
        return [
            MemberOut(
                id=member.id,
                status=member.status,
                display=(display or "Membre")
                if member.status == MemberStatus.ACTIVE
                else (member.display_hint or "***"),
            )
            for member, display in await self.groups.list_members(group_id)
        ]

    async def add_member(self, group_id: uuid.UUID, user: RequestContext, data: MemberAdd) -> MemberOut:
        """By email, nothing is looked up: an invitation that becomes a member when that person signs in (the answer
        never says whether the address has an account). By Keycloak subject, a member at once."""
        await self._get_manageable(group_id, user)
        try:
            if data.email is not None:
                normalized = normalize_email(data.email)
                member = await self.groups.add_member(
                    group_id, identifier_hash=hash_identifier(normalized), display_hint=mask_email(normalized)
                )
                display = member.display_hint or "***"
            else:
                member = await self.groups.add_member(group_id, user_id=data.user_id)
                display = "Membre"
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()
            raise AlreadyMemberError(str(group_id)) from error
        return MemberOut(id=member.id, status=member.status, display=display)

    async def remove_member(self, group_id: uuid.UUID, user: RequestContext, member_id: uuid.UUID) -> None:
        await self._get_manageable(group_id, user)
        member = await self.groups.get_member(group_id, member_id)
        if member is None:
            raise MemberNotFoundError(str(member_id))
        await self.groups.remove_member(member)
        await self.db.commit()
