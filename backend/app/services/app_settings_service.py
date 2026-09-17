from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.repositories.app_settings_repository import AppSettingsRepository
from app.schemas.app_settings import AppSettingsOut, AppSettingsUpdate


class NotAdminError(Exception):
    pass


class AppSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = AppSettingsRepository(db)

    async def get_settings(self, user: RequestContext) -> AppSettingsOut:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        settings = await self.repository.get()
        return AppSettingsOut(embedding_model=settings.embedding_model if settings else None)

    async def update_embedding_model(self, user: RequestContext, update: AppSettingsUpdate) -> AppSettingsOut:
        if not user.is_admin:
            raise NotAdminError(user.user_id)
        settings = await self.repository.set_embedding_model(update.embedding_model)
        await self.db.commit()
        return AppSettingsOut(embedding_model=settings.embedding_model)
