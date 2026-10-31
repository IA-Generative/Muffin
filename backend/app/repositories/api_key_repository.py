import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey


class ApiKeyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        user_id: str,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: datetime,
        owner_email: str | None,
        owner_groups: list[str],
    ) -> ApiKey:
        key = ApiKey(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            expires_at=expires_at,
            owner_email=owner_email,
            owner_groups=owner_groups,
        )
        self.db.add(key)
        await self.db.flush()
        await self.db.refresh(key, attribute_names=["created_at", "updated_at"])
        return key

    async def list_by_owner(self, user_id: str) -> Sequence[ApiKey]:
        result = await self.db.execute(
            select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
        )
        return result.scalars().all()

    async def count_usable(self, user_id: str, now: datetime) -> int:
        count = await self.db.scalar(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None), ApiKey.expires_at > now)
        )
        return count or 0

    async def get_owned(self, key_id: uuid.UUID, user_id: str) -> ApiKey | None:
        result = await self.db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_hashes(self, hashes: list[str]) -> ApiKey | None:
        result = await self.db.execute(select(ApiKey).where(ApiKey.key_hash.in_(hashes)))
        return result.scalar_one_or_none()

    async def touch(self, key_id: uuid.UUID, now: datetime, every_seconds: int) -> None:
        """Notes a use - at most once every `every_seconds`, so that a busy key does not write at each request."""
        await self.db.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key_id,
                or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < now - timedelta(seconds=every_seconds)),
            )
            .values(last_used_at=now)
        )

    async def refresh_owner(self, user_id: str, email: str | None, groups: list[str]) -> None:
        """What the keys of this user know of them, as they are now - called whenever they log in."""
        await self.db.execute(
            update(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
            .values(owner_email=email, owner_groups=groups)
        )
