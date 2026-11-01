import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory, UserMemorySettings


class MemoryRepository:
    """Every read and write is of one person's memory: no method takes anything but `user_id` to find an item."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def items(self, user_id: str) -> list[UserMemory]:
        result = await self.db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.kind, UserMemory.created_at)
        )
        return list(result.scalars())

    async def count(self, user_id: str) -> int:
        return int(
            await self.db.scalar(select(func.count()).select_from(UserMemory).where(UserMemory.user_id == user_id)) or 0
        )

    async def get(self, user_id: str, item_id: uuid.UUID) -> UserMemory | None:
        return await self.db.scalar(select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.id == item_id))

    async def by_key(self, user_id: str, kind: MemoryKind, key: str) -> UserMemory | None:
        return await self.db.scalar(
            select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.kind == kind, UserMemory.key == key)
        )

    async def usable(self, user_id: str) -> list[UserMemory]:
        """What a run may read: on, not expired - the most certain first, and what the person wrote before what was
        learned."""
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.enabled.is_(True),
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > now),
            )
            .order_by(
                (UserMemory.origin == MemoryOrigin.EXPLICIT).desc(),
                UserMemory.confidence.desc(),
                UserMemory.updated_at.desc(),
            )
        )
        return list(result.scalars())

    async def add(self, item: UserMemory) -> UserMemory:
        self.db.add(item)
        await self.db.flush()
        return item

    async def delete(self, item: UserMemory) -> None:
        await self.db.delete(item)
        await self.db.flush()

    async def delete_all(self, user_id: str) -> int:
        result = await self.db.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
        return int(result.rowcount or 0)

    async def touch(self, user_id: str, ids: list[uuid.UUID]) -> None:
        if ids:
            await self.db.execute(
                update(UserMemory)
                .where(UserMemory.user_id == user_id, UserMemory.id.in_(ids))
                .values(last_used_at=datetime.now(UTC))
            )

    async def enabled(self, user_id: str) -> bool:
        row = await self.db.get(UserMemorySettings, user_id)
        return True if row is None else row.enabled

    async def set_enabled(self, user_id: str, enabled: bool) -> None:
        await self.db.execute(
            insert(UserMemorySettings)
            .values(user_id=user_id, enabled=enabled)
            .on_conflict_do_update(index_elements=["user_id"], set_={"enabled": enabled, "updated_at": func.now()})
        )

    async def learning_from(self, user_id: str) -> datetime | None:
        row = await self.db.get(UserMemorySettings, user_id)
        return None if row is None else row.learning_from

    async def forget_learning_before_now(self, user_id: str) -> None:
        """What the person did until now is no longer learned from: they removed what it had taught."""
        now = datetime.now(UTC)
        await self.db.execute(
            insert(UserMemorySettings)
            .values(user_id=user_id, learning_from=now)
            .on_conflict_do_update(index_elements=["user_id"], set_={"learning_from": now, "updated_at": func.now()})
        )

    async def counts(self) -> dict[str, int]:
        """The only thing an administrator sees of the memories: how many, and of whom - never what."""
        people = await self.db.scalar(select(func.count(func.distinct(UserMemory.user_id))))
        items = await self.db.scalar(select(func.count()).select_from(UserMemory))
        off = await self.db.scalar(
            select(func.count()).select_from(UserMemorySettings).where(UserMemorySettings.enabled.is_(False))
        )
        return {"people": int(people or 0), "items": int(items or 0), "turned_off": int(off or 0)}
