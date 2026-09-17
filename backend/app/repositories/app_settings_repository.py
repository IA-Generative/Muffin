from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSettings

SETTINGS_ID = 1


class AppSettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> AppSettings | None:
        return await self.db.get(AppSettings, SETTINGS_ID)

    async def set_embedding_model(self, model: str) -> AppSettings:
        settings = await self.get()
        if settings is None:
            settings = AppSettings(id=SETTINGS_ID, embedding_model=model)
            self.db.add(settings)
        else:
            settings.embedding_model = model
        await self.db.flush()
        return settings
