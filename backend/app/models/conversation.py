from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
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
    # What made it when it was not the user in the chat: "api" for the OpenAI-compatible API (#513). Such a
    # conversation is not in the sidebar nor in the search, and is purged after a while.
    # The tools (see app/models/tool.py, `ToolService.ref`) the person removed for this conversation (#343): the model
    # is not given them. They only ever remove: a conversation never gains a tool its person may not use.
    disabled_tool_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

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
    # The lazily-created Collection backing files uploaded directly into this conversation (§
    # conv-files, see Collection.is_temporary/conversation_id) - None until the first upload.
    # cascade="all, delete-orphan" here even though the FK itself already has
    # ondelete="CASCADE": without it, SQLAlchemy's unit-of-work nulls out conversation_id on
    # session.delete(conversation) instead of trusting the DB-level cascade (same reasoning as
    # `messages` above) - confirmed by a real cascade-delete test, not just following convention.
    temporary_collection: Mapped["Collection | None"] = relationship(  # noqa: F821
        back_populates="conversation",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="Collection.conversation_id",
    )
