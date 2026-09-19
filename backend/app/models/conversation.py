from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    # Keycloak subject (sub) claim; no local users table, auth is delegated to Keycloak.
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # Starts as the first message's own text (truncated), then the agent_execution worker
    # rewrites it once from the first run's query+answer (see internal_runs.py's title route) -
    # this flag makes that rewrite a one-time, idempotent event instead of re-firing (and
    # burning an LLM call) on every later run in the same conversation.
    title_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    discussion_scores: Mapped[list["DiscussionScore"]] = relationship(  # noqa: F821
        back_populates="conversation", cascade="all, delete-orphan"
    )
    discussion_feedbacks: Mapped[list["DiscussionFeedback"]] = relationship(  # noqa: F821
        back_populates="conversation", cascade="all, delete-orphan"
    )
