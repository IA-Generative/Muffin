import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CguVersion(UUIDMixin, TimestampMixin, Base):
    """One version of the CGU (Conditions Générales d'Utilisation) - same create-then-activate
    pattern as PromptVersion (§96): a new version is never an edit in place, so the full history
    stays consultable and every CguAcceptance row keeps its exact meaning even after a newer
    version supersedes it (§127)."""

    __tablename__ = "cgu_versions"

    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CguAcceptance(UUIDMixin, TimestampMixin, Base):
    """One row per (user, CGU version) accepted - not just "has this user ever accepted the
    CGU" but the exact version and when (created_at, from TimestampMixin, doubles as the
    acceptance timestamp), kept even once a newer version is published, for transparency (§127:
    "cet utilisateur a accepté la v1 le [date], puis la v3 le [date]")."""

    __tablename__ = "cgu_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "cgu_version_id", name="uq_cgu_acceptances_user_version"),)

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    cgu_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cgu_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
