import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Source(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)

    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        secondary="message_sources", back_populates="sources"
    )


class MessageSource(Base):
    """Link table: sources cited by a message (optional, many-to-many)."""

    __tablename__ = "message_sources"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
