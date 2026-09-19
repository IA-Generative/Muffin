import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    text as sa_text,
)
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
    the cheaper, more conservative default.

    content_hash is a SHA-256 of the transcript the worker actually judged (role + content of
    every message, see worker/evaluation's score_discussion). Together with llm_model it forms a
    partial unique index: re-scoring the exact same conversation with the exact same model is a
    no-op - the worker skips it and returns the existing score instead of burning another LLM
    call. A conversation that grows (new turn) produces a different hash and gets re-scored.
    """

    __tablename__ = "discussion_scores"
    __table_args__ = (
        # Partial unique: only one score per (conversation, content, model). Partial (not full)
        # because we want to allow NULL hashes during the migration window - a backfill isn't
        # worth it for a table that starts empty.
        Index(
            "uq_discussion_scores_conv_hash_model",
            "conversation_id",
            "content_hash",
            "llm_model",
            unique=True,
            postgresql_where=sa_text("content_hash IS NOT NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 hex digest of the transcript the worker judged (see score_discussion in
    # worker/evaluation). Nullable only for rows created before this column existed.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
