import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import CollectionShare, ShareSubjectType
from app.models.group import Group, GroupMember, MemberStatus, ResourceSource
from app.models.token_usage import UserProfile


@dataclass(frozen=True)
class GroupSyncResult:
    group: Group
    created: bool
    members_added: int
    members_removed: int


class GroupRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def group_ids_of(self, user_id: str) -> list[str]:
        """The groups a user is a member of here, as what a share points to (a group's id)."""
        result = await self.db.scalars(
            select(GroupMember.group_id).where(
                GroupMember.user_id == user_id, GroupMember.status == MemberStatus.ACTIVE
            )
        )
        return [str(group_id) for group_id in result]

    async def _get_external(self, source: ResourceSource, external_id: str) -> Group | None:
        return await self.db.scalar(select(Group).where(Group.source == source, Group.external_id == external_id))

    async def sync_external(
        self, source: ResourceSource, external_id: str, name: str, description: str, member_ids: list[str]
    ) -> GroupSyncResult:
        """Makes the copy of a group of the other system what that system has: created if it was not there,
        renamed if it changed, and its members exactly `member_ids`."""
        group = await self._get_external(source, external_id)
        created = group is None
        if group is None:
            group = Group(name=name, description=description, source=source, external_id=external_id)
            self.db.add(group)
            await self.db.flush()
        else:
            group.name, group.description = name, description

        wanted = set(member_ids)
        current = set(await self.db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group.id)))
        removed = current - wanted
        added = wanted - current
        if removed:
            await self.db.execute(
                delete(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id.in_(removed))
            )
        self.db.add_all(GroupMember(group_id=group.id, user_id=user_id) for user_id in sorted(added))
        await self.db.flush()
        return GroupSyncResult(group, created, len(added), len(removed))

    async def external_ids(self, source: ResourceSource) -> list[str]:
        result = await self.db.scalars(
            select(Group.external_id).where(Group.source == source, Group.external_id.is_not(None))
        )
        return list(result)

    async def delete_external(self, source: ResourceSource, external_id: str) -> bool:
        group = await self._get_external(source, external_id)
        if group is None:
            return False
        await self.db.delete(group)
        await self.db.flush()
        return True

    # -- the groups people manage here (#455) ---------------------------------------------------------------

    async def list_visible(self, user_id: str, is_admin: bool) -> list[tuple[Group, int, int]]:
        """(group, active members, pending invitations) of the groups the caller owns or is in - all of them for
        an administrator - by name."""
        active = (
            select(GroupMember.group_id, func.count().label("n"))
            .where(GroupMember.status == MemberStatus.ACTIVE)
            .group_by(GroupMember.group_id)
            .subquery()
        )
        pending = (
            select(GroupMember.group_id, func.count().label("n"))
            .where(GroupMember.status == MemberStatus.PENDING)
            .group_by(GroupMember.group_id)
            .subquery()
        )
        statement = (
            select(Group, func.coalesce(active.c.n, 0), func.coalesce(pending.c.n, 0))
            .outerjoin(active, active.c.group_id == Group.id)
            .outerjoin(pending, pending.c.group_id == Group.id)
            .order_by(func.lower(Group.name))
        )
        if not is_admin:
            member_of = select(GroupMember.group_id).where(
                GroupMember.user_id == user_id, GroupMember.status == MemberStatus.ACTIVE
            )
            statement = statement.where(or_(Group.owner_id == user_id, Group.id.in_(member_of)))
        return [
            (group, int(n_active), int(n_pending)) for group, n_active, n_pending in (await self.db.execute(statement))
        ]

    async def get(self, group_id: uuid.UUID) -> Group | None:
        return await self.db.get(Group, group_id)

    async def is_member(self, group_id: uuid.UUID, user_id: str) -> bool:
        return (
            await self.db.scalar(
                select(GroupMember.id).where(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user_id,
                    GroupMember.status == MemberStatus.ACTIVE,
                )
            )
            is not None
        )

    async def create(self, owner_id: str, name: str, description: str) -> Group:
        group = Group(name=name, description=description, owner_id=owner_id)
        self.db.add(group)
        await self.db.flush()
        return group

    async def delete(self, group: Group) -> None:
        """The group, its members, and the shares of collections that pointed to it (a share holds the group's id
        as a plain string: nothing else would remove it)."""
        await self.db.execute(
            delete(CollectionShare).where(
                CollectionShare.subject_type == ShareSubjectType.GROUP,
                CollectionShare.subject_id == str(group.id),
            )
        )
        await self.db.delete(group)
        await self.db.flush()

    async def list_members(self, group_id: uuid.UUID) -> list[tuple[GroupMember, str | None]]:
        """The members with the name their profile shows, if they ever signed in: active ones first."""
        statement = (
            select(GroupMember, UserProfile.display)
            .outerjoin(UserProfile, UserProfile.user_id == GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.status, GroupMember.created_at)
        )
        return [(member, display) for member, display in (await self.db.execute(statement))]

    async def get_member(self, group_id: uuid.UUID, member_id: uuid.UUID) -> GroupMember | None:
        return await self.db.scalar(
            select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.id == member_id)
        )

    async def add_member(
        self,
        group_id: uuid.UUID,
        *,
        user_id: str | None = None,
        identifier_hash: str | None = None,
        display_hint: str | None = None,
    ) -> GroupMember:
        member = GroupMember(
            group_id=group_id,
            user_id=user_id,
            status=MemberStatus.ACTIVE if user_id is not None else MemberStatus.PENDING,
            invited_identifier_hash=identifier_hash,
            display_hint=display_hint,
        )
        self.db.add(member)
        await self.db.flush()
        return member

    async def remove_member(self, member: GroupMember) -> None:
        await self.db.delete(member)
        await self.db.flush()

    async def resolve_pending_members(self, identifier_hash: str, user_id: str) -> None:
        """Turns the invitations made under this email into members now that the person signed in (passive, like
        the shares: nothing the inviter does can trigger or observe it). An invitation to a group they already
        are in by their subject is just dropped."""
        already_in = select(GroupMember.group_id).where(
            GroupMember.user_id == user_id, GroupMember.status == MemberStatus.ACTIVE
        )
        await self.db.execute(
            delete(GroupMember).where(
                GroupMember.status == MemberStatus.PENDING,
                GroupMember.invited_identifier_hash == identifier_hash,
                GroupMember.group_id.in_(already_in),
            )
        )
        await self.db.execute(
            update(GroupMember)
            .where(GroupMember.status == MemberStatus.PENDING, GroupMember.invited_identifier_hash == identifier_hash)
            .values(status=MemberStatus.ACTIVE, user_id=user_id, invited_identifier_hash=None, display_hint=None)
        )
