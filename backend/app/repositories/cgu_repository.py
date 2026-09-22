import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cgu import CguAcceptance, CguVersion


class CguRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active(self) -> CguVersion | None:
        result = await self.db.execute(select(CguVersion).where(CguVersion.is_active.is_(True)))
        return result.scalar_one_or_none()

    async def list_versions(self) -> list[CguVersion]:
        result = await self.db.execute(select(CguVersion).order_by(CguVersion.version.desc()))
        return list(result.scalars())

    async def get_version(self, version: int) -> CguVersion | None:
        result = await self.db.execute(select(CguVersion).where(CguVersion.version == version))
        return result.scalar_one_or_none()

    async def create_version(self, content: str) -> CguVersion:
        result = await self.db.execute(select(func.max(CguVersion.version)))
        next_version = (result.scalar_one_or_none() or 0) + 1
        cgu_version = CguVersion(version=next_version, content=content, is_active=False)
        self.db.add(cgu_version)
        await self.db.flush()
        return cgu_version

    async def activate(self, version: int) -> CguVersion | None:
        """Deactivates whatever version is currently active (if any) and activates this one
        instead - a rollback is just activating an older version, same method."""
        target = await self.get_version(version)
        if target is None:
            return None
        current = await self.get_active()
        if current is not None and current.id != target.id:
            current.is_active = False
        target.is_active = True
        await self.db.flush()
        return target

    async def get_acceptance(self, user_id: str, cgu_version_id: uuid.UUID) -> CguAcceptance | None:
        result = await self.db.execute(
            select(CguAcceptance).where(
                CguAcceptance.user_id == user_id, CguAcceptance.cgu_version_id == cgu_version_id
            )
        )
        return result.scalar_one_or_none()

    async def has_any_acceptance(self, user_id: str) -> bool:
        """Whether this user has ever accepted *any* version - not the current one specifically
        (that's get_acceptance) - used to tell a first-time acceptance apart from a re-acceptance
        after the CGU changed (§127: the screen must say "mise à jour", not present itself as a
        first visit, when this is true)."""
        result = await self.db.execute(select(CguAcceptance.id).where(CguAcceptance.user_id == user_id).limit(1))
        return result.scalar_one_or_none() is not None

    async def record_acceptance(self, user_id: str, cgu_version_id: uuid.UUID) -> CguAcceptance:
        existing = await self.get_acceptance(user_id, cgu_version_id)
        if existing is not None:
            return existing  # idempotent - a duplicate "j'accepte" click must never fail
        acceptance = CguAcceptance(user_id=user_id, cgu_version_id=cgu_version_id)
        self.db.add(acceptance)
        await self.db.flush()
        return acceptance
