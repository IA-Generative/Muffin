import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DiscussionScore(UUIDMixin, TimestampMixin, Base):
    """A quality judgment over a whole conversation (see #31) - distinct from #32's groundedness
    (which judges whether one answer's claims are supported by its own sources): this judges the
    conversation as a whole, across turns - contradictions between successive answers, and
    whether a follow-up question's conversational context ("et pour elle ?") was actually
    understood and used. Computed on demand (worker/evaluation, see app/tasks.py's
    score_discussion), never automatically on every run - an LLM judgment call per conversation
    isn't free, and #31 left "on demand vs continuous" as an open question, so this starts with
    the cheaper, more conservative default."""

    __tablename__ = "discussion_scores"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # How many messages were actually in the transcript judged - context for reading the verdict
    # below (a "coherent" judgment over 2 messages carries a lot less weight than over 20).
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)

    coherent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Short descriptions of specific contradictions found between turns, empty if none.
    coherence_issues: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # 0.0-1.0: how well follow-up questions' conversational context was resolved and used, not a
    # boolean like `coherent` - context usage is rarely all-or-nothing across a whole thread.
    context_usage_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Short descriptions of turns where context was mishandled, empty if none.
    context_usage_issues: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="discussion_scores")  # noqa: F821
