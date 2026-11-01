import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

# The most an administrator may let one image weigh by default, and what a new installation allows per person per day.
DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_DAILY_LIMIT = 20


class ImageGenerationSettings(Base):
    """The generation of images in the chat (#518): one row (id is always 1), admin-only, **off by default**.

    The address of the provider and its key are the hub's when left empty. A key an administrator types is kept
    encrypted (`StoredSecret`, purpose `image-generation-key`) and never read back: the settings say only that there is
    one."""

    __tablename__ = "image_generation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # An OpenAI-compatible address ending in /v1; None: the hub's.
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size: Mapped[str] = mapped_column(String(20), nullable=False, default="1024x1024", server_default="1024x1024")
    quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Images one person may make per day (UTC), and the heaviest one that is kept (bytes).
    daily_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_DAILY_LIMIT, server_default=str(DEFAULT_DAILY_LIMIT)
    )
    max_image_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_IMAGE_BYTES, server_default=str(DEFAULT_MAX_IMAGE_BYTES)
    )
    # Keycloak groups or groups of Muffin that may generate; empty: everyone. An administrator always may.
    allowed_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GeneratedImage(UUIDMixin, TimestampMixin, Base):
    """An image a person asked for in the chat (#518), stored by Muffin: the answer of the provider is never given on
    as it is (an address of its own expires and points at a third party), and the image is the conversation's - read by
    its owner only, and deleted with it. It belongs to the message that shows it."""

    __tablename__ = "generated_images"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # The run that asked for it, when the assistant did (the tool `generer_image`): the image belongs to the run first,
    # and to the message once the run's answer is one - like a chart. None for an image asked for with the mode «Image».
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    # RustFS key: images/{conversation_id}/{image_id}.{png|jpg|webp}
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
