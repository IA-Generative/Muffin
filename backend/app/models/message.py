import enum
import uuid
from typing import Any

from sqlalchemy import Computed, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_content_tsv", "content_tsv", postgresql_using="gin"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The words of `content` for the search of the conversations (#509), kept by the database itself and only ever
    # read by that search: deferred, so that no other query carries it.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('muffin_french'::regconfig, content)", persisted=True), deferred=True
    )
    # Only ever set for an ASSISTANT message (the run that produced it) - SET NULL rather than
    # CASCADE so a run being cleaned up later never silently deletes chat history with it. Lets
    # the frontend re-fetch that run's citations/event trace ("execution detail") for a message
    # restored from history, not just a live one still in memory.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Agent response latency in milliseconds - only set on ASSISTANT messages, measured by
    # the agent worker around the generate_answer LLM call. Used by the quality dashboard
    # to compute average response latency.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Token usage from the LLM call that produced this message - only set on ASSISTANT messages.
    # prompt_tokens = tokens sent to the LLM, completion_tokens = tokens received back.
    # Used by the quality dashboard for cost estimation (0.75 × total tokens).
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The multiple-choice questions the assistant asked instead of answering (#344), as the worker
    # sanitized them: [{"question", "header", "multi_select", "options": [{"label", "description"}]}].
    # `content` holds the same questions as text, which is what the next run's history carries.
    questions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # What the user answered: [{"selected": [labels], "text": free text or None}], one per question. None
    # while unanswered - and for good when the user wrote something else instead, which abandons the
    # questions (see ConversationService.list_messages).
    questions_answer: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # A user message the guardrails on the input masked (#516): what the models see of it, in this turn and in the next
    # ones. `content` stays what the person wrote - it is theirs. `guardrail_action`: `redacted`, `blocked`, `warned`.
    redacted_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardrail_action: Mapped[str | None] = mapped_column(String(16), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")  # noqa: F821
    sources: Mapped[list["Source"]] = relationship(  # noqa: F821
        secondary="message_sources", back_populates="messages"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(  # noqa: F821
        back_populates="message", cascade="all, delete-orphan"
    )
