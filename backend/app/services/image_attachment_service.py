"""The images a person attaches to a message for the model to read (#512).

Rules this keeps to:
- **Offered only when a model can read them.** Without a model of the hub that reads images, nothing is accepted, and
  the chat says so - rather than an image sent to a model that ignores it, or an answer silently coming from another.
- **The bytes are checked, not the sender's word** (`app/core/image_bytes.py`): PNG, JPEG or WebP, never an SVG, of a
  bounded weight and size. A file whose content is not the type it claims is refused.
- **An image is chosen before the message exists**, so it is *staged*: stored and owned by its person, without a
  conversation, until the run that carries it claims it. What was chosen and never sent is cleaned up the next time the
  person chooses one (and by the limit on how many may wait).
- **It is theirs**: read by its owner only, through the backend, and deleted with its conversation."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ImageSettings
from app.core import image_bytes, storage
from app.core.image_bytes import NotAnImageError
from app.core.security.factory import RequestContext
from app.models.message_image import ORIGIN_ATTACHED, MessageImage
from app.repositories.message_image_repository import MessageImageRepository
from app.schemas.image_attachment import AttachmentOut, AttachmentStatusOut

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ImageSettings()

TYPES = ["image/png", "image/jpeg", "image/webp"]


class AttachmentError(Exception):
    """An image that cannot be attached, said with a code that does not change and words for the person."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


async def vision_models() -> list[str]:
    """The models of the hub that read images (cached, like the list of chat models). Empty when the hub cannot be
    asked: a function that depends on it is then simply not offered. A module function so that tests change it."""
    from app.routers.models import VISION_CACHE_KEY, _list_models, _supports_vision

    try:
        listed = await _list_models(VISION_CACHE_KEY, _supports_vision)
    except Exception:
        logger.warning("The models that read images could not be listed", exc_info=True)
        return []
    return [model.id for model in listed.models]


class ImageAttachmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.images = MessageImageRepository(db)

    async def status(self) -> AttachmentStatusOut:
        models = await vision_models()
        return AttachmentStatusOut(
            available=bool(models),
            model=models[0] if models else None,
            max_images=_settings.IMAGES_PER_MESSAGE,
            max_bytes=_settings.IMAGES_ATTACH_MAX_BYTES,
            types=TYPES,
        )

    async def _require_vision(self) -> None:
        if not await vision_models():
            raise AttachmentError(
                "pas_de_modele_vision",
                "Aucun modèle capable de lire les images n'est disponible : les images ne peuvent pas être jointes.",
                409,
            )

    async def stage(self, user: RequestContext, data: bytes) -> AttachmentOut:
        """Keeps an image the person chose, until the message that carries it is sent."""
        await self._require_vision()
        if len(data) > _settings.IMAGES_ATTACH_MAX_BYTES:
            raise AttachmentError("image_trop_lourde", "Cette image est trop lourde.", 413)
        try:
            info = image_bytes.inspect(data, max_side=_settings.IMAGES_MAX_SIDE)
        except NotAnImageError as error:
            raise AttachmentError("image_invalide", f"Ce fichier n'est pas utilisable : {error}", 422) from error
        await self._forget_stale(user.user_id)
        if await self.images.count_staged(user.user_id) >= _settings.IMAGES_STAGED_MAX:
            raise AttachmentError(
                "trop_d_images", "Trop d'images en attente : envoyez votre message ou retirez-en.", 409
            )
        image_id = uuid.uuid4()
        key = f"images/attached/{image_id}.{info.extension}"
        await asyncio.to_thread(storage.put_object, key, data, info.content_type)
        try:
            await self.images.add(
                MessageImage(
                    id=image_id,
                    origin=ORIGIN_ATTACHED,
                    user_id=user.user_id,
                    s3_key=key,
                    content_type=info.content_type,
                    width=info.width,
                    height=info.height,
                    size_bytes=len(data),
                )
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            await asyncio.to_thread(storage.delete_objects, [key])
            raise
        return AttachmentOut(
            id=image_id, content_type=info.content_type, width=info.width, height=info.height, size_bytes=len(data)
        )

    async def _forget_stale(self, user_id: str) -> None:
        """What this person chose long ago and never sent: nothing refers to it any more. Best effort."""
        try:
            before = datetime.now(UTC) - timedelta(hours=_settings.IMAGES_STAGED_TTL_HOURS)
            stale = await self.images.stale_staged(user_id, before)
            for image in stale:
                await self.images.delete(image)
            await self.db.commit()
            if stale:
                await asyncio.to_thread(storage.delete_objects, [image.s3_key for image in stale])
        except Exception:
            await self.db.rollback()
            logger.warning("Images that were never sent could not be cleaned up", exc_info=True)

    async def read(self, user: RequestContext, image_id: uuid.UUID) -> tuple[bytes, str]:
        """An image the person chose and has not sent yet - theirs only - to show it in the composer."""
        image = await self.images.get_staged(image_id, user.user_id)
        if image is None:
            raise AttachmentError("image_introuvable", "Cette image n'existe pas.", 404)
        content, _ = await asyncio.to_thread(storage.get_object, image.s3_key)
        return content, image.content_type

    async def discard(self, user: RequestContext, image_id: uuid.UUID) -> None:
        image = await self.images.get_staged(image_id, user.user_id)
        if image is None:
            raise AttachmentError("image_introuvable", "Cette image n'existe pas.", 404)
        key = image.s3_key
        await self.images.delete(image)
        await self.db.commit()
        await asyncio.to_thread(storage.delete_objects, [key])

    # --- what a message carries ---

    async def check(self, user: RequestContext, image_ids: list[uuid.UUID]) -> None:
        """Before anything is written for a message: the images it names are allowed, and are the person's. Nothing is
        claimed yet."""
        if not image_ids:
            return
        if len(set(image_ids)) != len(image_ids) or len(image_ids) > _settings.IMAGES_PER_MESSAGE:
            raise AttachmentError("trop_d_images", f"Au plus {_settings.IMAGES_PER_MESSAGE} images par message.", 422)
        await self._require_vision()
        for image_id in image_ids:
            if await self.images.get_staged(image_id, user.user_id) is None:
                raise AttachmentError(
                    "image_introuvable", "Une image jointe n'existe plus : joignez-la de nouveau.", 422
                )

    async def claim(
        self, user: RequestContext, image_ids: list[uuid.UUID], conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> list[MessageImage]:
        """The images become the message's: its conversation's from now on, and deleted with it."""
        if not image_ids:
            return []
        claimed = await self.images.claim(image_ids, user.user_id, conversation_id, message_id)
        if len(claimed) != len(image_ids):
            raise AttachmentError("image_introuvable", "Une image jointe n'existe plus : joignez-la de nouveau.", 422)
        return claimed
