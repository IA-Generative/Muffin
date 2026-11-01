from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

# How long a notification is kept, read or not.
RETENTION_DAYS = 90

CHANNEL_APP = "app"


class Notification(UUIDMixin, Base):
    """Something the application tells a person (#524): a routine that ran, a document that failed, a share received.
    Theirs alone. It holds what the person can already read in the application - a title, one line and a link - and
    never the text of an answer; `data` holds identifiers (the routine, the conversation) and nothing else."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    # A path of the application (`/c/…`, `/routines`), never an address of another site.
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class NotificationPreference(Base):
    """Whether a person wants the notifications of a type, by channel. No row means the default: in the application,
    yes (the other channels are not offered yet)."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String(48), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), primary_key=True, default=CHANNEL_APP, server_default=CHANNEL_APP)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
