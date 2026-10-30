from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group, GroupMember, MemberStatus, ResourceSource


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
