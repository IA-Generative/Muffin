import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import PromptVersion, RunPromptUsage


class PromptRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active(self, name: str) -> PromptVersion | None:
        result = await self.db.execute(
            select(PromptVersion).where(PromptVersion.name == name, PromptVersion.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[PromptVersion]:
        result = await self.db.execute(
            select(PromptVersion).where(PromptVersion.is_active.is_(True)).order_by(PromptVersion.name)
        )
        return list(result.scalars())

    async def list_versions(self, name: str) -> list[PromptVersion]:
        result = await self.db.execute(
            select(PromptVersion).where(PromptVersion.name == name).order_by(PromptVersion.version.desc())
        )
        return list(result.scalars())

    async def get_version(self, name: str, version: int) -> PromptVersion | None:
        result = await self.db.execute(
            select(PromptVersion).where(PromptVersion.name == name, PromptVersion.version == version)
        )
        return result.scalar_one_or_none()

    async def create_version(self, name: str, content: str) -> PromptVersion:
        result = await self.db.execute(select(func.max(PromptVersion.version)).where(PromptVersion.name == name))
        next_version = (result.scalar_one_or_none() or 0) + 1
        prompt_version = PromptVersion(name=name, version=next_version, content=content, is_active=False)
        self.db.add(prompt_version)
        await self.db.flush()
        return prompt_version

    async def activate(self, name: str, version: int) -> PromptVersion | None:
        """Deactivates whatever version of `name` is currently active (if any) and activates
        this one instead - a rollback is just activating an older version, same method."""
        target = await self.get_version(name, version)
        if target is None:
            return None
        current = await self.get_active(name)
        if current is not None and current.id != target.id:
            current.is_active = False
        target.is_active = True
        await self.db.flush()
        return target

    async def record_usages(self, run_id: uuid.UUID, prompt_version_ids: list[uuid.UUID]) -> None:
        self.db.add_all(
            [RunPromptUsage(run_id=run_id, prompt_version_id=version_id) for version_id in prompt_version_ids]
        )
        await self.db.flush()
