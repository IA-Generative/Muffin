from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.prompt import PromptVersion
from app.repositories.prompt_repository import PromptRepository


class NotAdminError(Exception):
    pass


class PromptNotFoundError(Exception):
    pass


class PromptService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = PromptRepository(db)

    async def list_summaries(self, user: RequestContext) -> list[PromptVersion]:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        # Whichever prompts have ever been seeded/created, not a hardcoded list here - the six
        # node prompts are seeded by migration, so this always reflects what actually exists.
        return await self.repository.list_active()

    async def list_versions(self, user: RequestContext, name: str) -> list[PromptVersion]:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        return await self.repository.list_versions(name)

    async def create_version(self, user: RequestContext, name: str, content: str) -> PromptVersion:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        version = await self.repository.create_version(name, content)
        await self.db.commit()
        return version

    async def activate(self, user: RequestContext, name: str, version: int) -> PromptVersion:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        activated = await self.repository.activate(name, version)
        if activated is None:
            raise PromptNotFoundError(f"{name} v{version}")
        await self.db.commit()
        return activated
