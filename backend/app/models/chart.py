import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Chart(UUIDMixin, TimestampMixin, Base):
    """A chart the agent drew to illustrate an answer (#434): the description it asked for, and the PNG in RustFS.

    The agent draws while the run is going, before its answer is a message: the chart belongs to the run first, and to
    the message once it is created (`message_id`). It is served by the backend only, with the rights of the
    conversation - never a link to the bucket - and goes with the conversation (and its image with it)."""

    __tablename__ = "charts"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # What was asked: {type, x, y, color, title, x_label, y_label, stacked, sort}. Data, never code.
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    # RustFS key of the PNG: charts/{conversation_id}/{chart_id}.png
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    # Only a chart that was drawn is kept: "ready".
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready", server_default="ready")
