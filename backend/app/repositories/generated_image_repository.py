import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_generation import GeneratedImage, ImageGenerationSettings


class GeneratedImageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, image: GeneratedImage) -> GeneratedImage:
        self.db.add(image)
        await self.db.flush()
        return image

    async def get_in_conversation(self, image_id: uuid.UUID, conversation_id: uuid.UUID) -> GeneratedImage | None:
        result = await self.db.execute(
            select(GeneratedImage).where(
                GeneratedImage.id == image_id, GeneratedImage.conversation_id == conversation_id
            )
        )
        return result.scalar_one_or_none()

    async def for_messages(self, message_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[GeneratedImage]]:
        if not message_ids:
            return {}
        result = await self.db.execute(
            select(GeneratedImage).where(GeneratedImage.message_id.in_(message_ids)).order_by(GeneratedImage.created_at)
        )
        by_message: dict[uuid.UUID, list[GeneratedImage]] = {}
        for image in result.scalars():
            if image.message_id is not None:
                by_message.setdefault(image.message_id, []).append(image)
        return by_message

    async def attach_to_message(self, image_id: uuid.UUID, message_id: uuid.UUID) -> None:
        await self.db.execute(update(GeneratedImage).where(GeneratedImage.id == image_id).values(message_id=message_id))

    async def keys_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[str]:
        result = await self.db.execute(
            select(GeneratedImage.s3_key).where(GeneratedImage.conversation_id == conversation_id)
        )
        return result.scalars().all()


class ImageSettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> ImageGenerationSettings | None:
        return await self.db.get(ImageGenerationSettings, 1)

    async def get_or_create(self) -> ImageGenerationSettings:
        settings = await self.get()
        if settings is None:
            settings = ImageGenerationSettings(id=1)
            self.db.add(settings)
            await self.db.flush()
            await self.db.refresh(settings)
        return settings
