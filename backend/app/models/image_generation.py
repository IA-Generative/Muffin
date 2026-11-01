import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

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
