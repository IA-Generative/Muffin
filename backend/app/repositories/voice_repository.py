from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceEngineSettings


class VoiceSettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> VoiceEngineSettings | None:
        return await self.db.get(VoiceEngineSettings, 1)

    async def get_or_create(self) -> VoiceEngineSettings:
        settings = await self.get()
        if settings is None:
            settings = VoiceEngineSettings(id=1)
            self.db.add(settings)
            await self.db.flush()
            await self.db.refresh(settings)
        return settings
