import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Source(UUIDMixin, TimestampMixin, Base):
    """A normalized copy of one citation the agent produced (see worker/agent_execution/app/
    graph/nodes/generate_answer.py's `citations`), materialized so a stable id exists to
    validate/add in feedback (see FeedbackSource) - Run.citations (JSONB) stays the source of
    truth for what's *shown* in the chat, this is only about giving it an identity."""

    __tablename__ = "sources"

    title: Mapped[str] = mapped_column(String, nullable=False)
    # Set only for a web_search citation (a real, external URL) - null for an internal document
    # citation, identified by document_id/chunk_id/page_number instead.
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    # SET NULL, not CASCADE: a source deleted alongside its document must not silently delete the
    # feedback/message history that references it (same reasoning as Message.run_id).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        secondary="message_sources", back_populates="sources"
    )


class MessageSource(Base):
    """Link table: sources cited by a message (optional, many-to-many)."""

    __tablename__ = "message_sources"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
