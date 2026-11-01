import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class MemoryKind(enum.StrEnum):
    PREFERENCE = "preference"
    HABIT = "habit"
    CONTEXT = "context"
    FACT = "fact"


class MemoryOrigin(enum.StrEnum):
    # Written, corrected or asked for by the person: what is learned never overwrites it.
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class UserMemory(UUIDMixin, TimestampMixin, Base):
    """One thing the assistant remembers of a person (#282): how they like answers, their context, what they asked to
    remember. Personal: it is read for nobody else - not an administrator, not another user - and it shapes the form of
    an answer, never its content: it is no proof and no citation."""

    __tablename__ = "user_memories"
    __table_args__ = (UniqueConstraint("user_id", "kind", "key", name="uq_user_memories_user_kind_key"),)

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    kind: Mapped[MemoryKind] = mapped_column(Enum(MemoryKind, name="memory_kind"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[MemoryOrigin] = mapped_column(Enum(MemoryOrigin, name="memory_origin"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What a learned habit is about and how much it weighs (#286): {"collection_id", "score", "at"}. None for everything
    # that is a sentence - what a habit says to the person is `value`; what the routing reads is here, never a prompt.
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class UserMemorySettings(Base):
    """Whether a person's memory is on. A person without a row has it on: it is turned off by choice, at any time, and
    then nothing is read nor learned - what was kept stays until the person deletes it."""

    __tablename__ = "user_memory_settings"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Nothing the person did before this moment is learned from any more (#285): set when they delete something that was
    # learned, so that what they removed does not come back with the next 👍.
    learning_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
