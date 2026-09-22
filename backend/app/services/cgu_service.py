from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.cgu import CguVersion
from app.repositories.cgu_repository import CguRepository


class NotAdminError(Exception):
    pass


class CguVersionNotFoundError(Exception):
    pass


class CguStatus:
    def __init__(self, version: int | None, content: str | None, accepted: bool, is_update: bool) -> None:
        self.version = version
        self.content = content
        self.accepted = accepted
        self.is_update = is_update


class CguService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = CguRepository(db)

    async def get_status(self, user: RequestContext) -> CguStatus:
        """§127: the active version's content plus whether *this* user has accepted it - and,
        if not, whether this is their first-ever CGU screen or a re-acceptance after an update
        (they'd already accepted some earlier version), so the frontend can say "mise à jour"
        rather than presenting a re-acceptance as if it were day one."""
        active = await self.repository.get_active()
        if active is None:
            # Nothing configured yet (shouldn't happen once the seed migration has run, but
            # never block the app over a missing row) - treated as already accepted.
            return CguStatus(version=None, content=None, accepted=True, is_update=False)

        accepted = await self.repository.get_acceptance(user.user_id, active.id) is not None
        is_update = not accepted and await self.repository.has_any_acceptance(user.user_id)
        return CguStatus(version=active.version, content=active.content, accepted=accepted, is_update=is_update)

    async def accept(self, user: RequestContext) -> CguStatus:
        active = await self.repository.get_active()
        if active is None:
            raise CguVersionNotFoundError("no active CGU version")
        await self.repository.record_acceptance(user.user_id, active.id)
        await self.db.commit()
        return CguStatus(version=active.version, content=active.content, accepted=True, is_update=False)

    async def list_versions(self, user: RequestContext) -> list[CguVersion]:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        return await self.repository.list_versions()

    async def create_version(self, user: RequestContext, content: str) -> CguVersion:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        version = await self.repository.create_version(content)
        await self.db.commit()
        return version

    async def activate(self, user: RequestContext, version: int) -> CguVersion:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        activated = await self.repository.activate(version)
        if activated is None:
            raise CguVersionNotFoundError(f"v{version}")
        await self.db.commit()
        return activated
