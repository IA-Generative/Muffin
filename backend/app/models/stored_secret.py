from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class StoredSecret(UUIDMixin, TimestampMixin, Base):
    """A secret Muffin must read back to use it - the key of a service it calls for someone, a connector's token (#521).
    Only its ciphertext is kept: see app/core/secret_store. Nothing here, nor in any answer of the API, shows it."""

    __tablename__ = "stored_secrets"

    # Keycloak subject of the person it belongs to; None for a secret of the deployment, set by an administrator.
    owner_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # What it is for ("transcription.api_key"): fixed by the code that stores it, and part of what the ciphertext is
    # bound to.
    purpose: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    # The version of the key the ciphertext was made with, so that the ones to rewrap after a rotation are found without
    # opening anything.
    key_version: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # The last characters of a long secret, to tell secrets apart on a screen ("••••a1b2"): empty for a short one.
    hint: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
