import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_generation import ImageGenerationSettings
from app.models.message_image import ORIGIN_ATTACHED, MessageImage


class MessageImageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, image: MessageImage) -> MessageImage:
        self.db.add(image)
        await self.db.flush()
        return image

    async def get_in_conversation(self, image_id: uuid.UUID, conversation_id: uuid.UUID) -> MessageImage | None:
        result = await self.db.execute(
            select(MessageImage).where(MessageImage.id == image_id, MessageImage.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def for_messages(self, message_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[MessageImage]]:
        if not message_ids:
            return {}
        result = await self.db.execute(
            select(MessageImage).where(MessageImage.message_id.in_(message_ids)).order_by(MessageImage.created_at)
        )
        by_message: dict[uuid.UUID, list[MessageImage]] = {}
        for image in result.scalars():
            if image.message_id is not None:
                by_message.setdefault(image.message_id, []).append(image)
        return by_message

    async def attach_run_to_message(self, run_id: uuid.UUID, message_id: uuid.UUID) -> None:
        """The images a run made while it ran belong to the message made from its answer, like its charts."""
        await self.db.execute(update(MessageImage).where(MessageImage.run_id == run_id).values(message_id=message_id))

    async def for_run(self, run_id: uuid.UUID) -> list[MessageImage]:
        result = await self.db.execute(
            select(MessageImage).where(MessageImage.run_id == run_id).order_by(MessageImage.created_at)
        )
        return list(result.scalars())

    async def keys_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[str]:
        result = await self.db.execute(
            select(MessageImage.s3_key).where(MessageImage.conversation_id == conversation_id)
        )
        return result.scalars().all()

    # --- the images a person attached, before the message that carries them exists ---

    async def get_staged(self, image_id: uuid.UUID, user_id: str) -> MessageImage | None:
        result = await self.db.execute(
            select(MessageImage).where(
                MessageImage.id == image_id,
                MessageImage.user_id == user_id,
                MessageImage.origin == ORIGIN_ATTACHED,
                MessageImage.message_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def count_staged(self, user_id: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(MessageImage)
            .where(
                MessageImage.user_id == user_id,
                MessageImage.origin == ORIGIN_ATTACHED,
                MessageImage.message_id.is_(None),
            )
        )
        return result.scalar_one()

    async def stale_staged(self, user_id: str, before: datetime) -> list[MessageImage]:
        """What a person chose and never sent: nothing refers to it any more."""
        result = await self.db.execute(
            select(MessageImage).where(
                MessageImage.user_id == user_id,
                MessageImage.origin == ORIGIN_ATTACHED,
                MessageImage.message_id.is_(None),
                MessageImage.created_at < before,
            )
        )
        return list(result.scalars())

    async def claim(
        self, image_ids: Sequence[uuid.UUID], user_id: str, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> list[MessageImage]:
        """The images the person attached to this message: theirs, attached and not yet sent. Fewer than asked means one
        was not - someone else's, already sent, or gone - and the caller refuses the whole message."""
        result = await self.db.execute(
            update(MessageImage)
            .where(
                MessageImage.id.in_(image_ids),
                MessageImage.user_id == user_id,
                MessageImage.origin == ORIGIN_ATTACHED,
                MessageImage.message_id.is_(None),
            )
            .values(conversation_id=conversation_id, message_id=message_id)
            .returning(MessageImage)
        )
        return list(result.scalars())

    async def delete(self, image: MessageImage) -> None:
        await self.db.delete(image)
        await self.db.flush()


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
