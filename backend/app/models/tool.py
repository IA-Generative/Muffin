import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

VISIBILITY_PRIVATE = "private"
VISIBILITY_GROUPS = "groups"
VISIBILITY_ALL = "all"
AUTH_NONE = "none"
AUTH_BEARER = "bearer"


class ToolServer(UUIDMixin, TimestampMixin, Base):
    """An MCP server a person added (#343), whose tools the chat may call. Muffin is its client."""

    __tablename__ = "tool_servers"

    # Keycloak subject of whoever added it.
    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # "none", or "bearer": a token kept encrypted (StoredSecret, purpose `tool-server-token`), never read back.
    auth_mode: Mapped[str] = mapped_column(String(8), nullable=False, default=AUTH_NONE, server_default=AUTH_NONE)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Who may use its tools besides its owner: nobody, the people in `group_ids` (Keycloak groups or groups of Muffin),
    # or everyone.
    visibility: Mapped[str] = mapped_column(
        String(8), nullable=False, default=VISIBILITY_PRIVATE, server_default=VISIBILITY_PRIVATE
    )
    group_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    tools: Mapped[list["Tool"]] = relationship(back_populates="server", cascade="all, delete-orphan", lazy="selectin")


class Tool(UUIDMixin, TimestampMixin, Base):
    """One tool of a server, as its `tools/list` described it - taken again each time the server is synchronised."""

    __tablename__ = "tools"

    server_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Whether it changes data somewhere (the server's `readOnlyHint` being false, or absent: not known to be safe).
    # Such a tool is never called without the person's approval - until that exists, it is not called at all.
    side_effect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    server: Mapped["ToolServer"] = relationship(back_populates="tools")

    __table_args__ = (UniqueConstraint("server_id", "name", name="uq_tool_server_name"),)


class ToolCallLog(UUIDMixin, TimestampMixin, Base):
    """The journal of the calls: who, which tool, how long, how it ended. Never the arguments nor the answer, which may
    hold personal data."""

    __tablename__ = "tool_call_logs"

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    # `internal.calculatrice` or the id of the tool of a server; the server is named too while it exists.
    tool_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    server_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # `ok`, or a stable code: quota_depasse, outil_indisponible, arguments_invalides, url_refusee, delai_depasse...
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REFUSED = "refused"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"
STATUS_SUPERSEDED = "superseded"
STATUS_EXPIRED = "expired"


class ChatToolCall(UUIDMixin, TimestampMixin, Base):
    """A request to run a tool that changes data (#343): the agent asked, nothing was run, and the person decides
    when they like. The discussion is the state - there is no task waiting.

    pending -> approved -> executed | failed, or pending -> refused | superseded (the person wrote something else
    instead of deciding) | expired (nobody decided in time). Only `pending` can be decided, once: the decision takes
    the row with a conditional update, so two clicks never run a tool twice."""

    __tablename__ = "chat_tool_calls"

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The run that asked: the calls of one turn are decided together.
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    tool_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    server_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # What the person is shown and agrees to - the arguments as the agent gave them, bounded and checked against the
    # schema.
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=STATUS_PENDING, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The code the run ended with (the codes of ToolCallResult) - never the answer, which goes to the discussion.
    result_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
