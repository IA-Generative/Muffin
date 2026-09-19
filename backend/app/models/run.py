import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Run(UUIDMixin, TimestampMixin, Base):
    """A research agent run. The source of truth for its lifecycle - the
    Celery task executing it (see backend/app/core/agent_tasks.py) reads and
    writes this row rather than keeping state in worker memory, so a worker
    restart, a resume after HITL, or a status check never depend on the
    task's own process being alive."""

    __tablename__ = "runs"

    # Keycloak subject (sub); identity always comes from the authenticated
    # request context, never from the LLM or the run's own payload.
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # Strong, non-nullable link to the user message that triggered this run -
    # a run always exists *because* of one specific message, never floating
    # free in a conversation. conversation_id is kept alongside it (instead
    # of only reachable via message.conversation_id) purely so "list runs in
    # this conversation" doesn't need a join; it must always equal
    # message.conversation_id (enforced in RunRepository.create, which loads
    # the message to derive it rather than trusting a caller-supplied value).
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    # Collections explicitly attached via the chat composer's "+" picker (§ user-pinned
    # collections) - stored as plain strings, same reasoning as citations below: read back
    # as-is by the worker, never queried/filtered on at the SQL level.
    pinned_collection_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Snapshot of RequestContext.groups at run creation time - the worker's load_accessible_vdbs
    # node needs this to resolve group-shared collections (see CollectionRepository.
    # list_all_accessible), and has no session/token of its own to read it from live. A snapshot,
    # not a live lookup, same tradeoff as pinned_collection_ids above: a group membership change
    # mid-run is not expected to retroactively change what an already-running query can reach.
    user_groups: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Opt-in per message (chat composer toggle, see RunCreate.web_search_enabled) - snapshotted
    # here for the same reason as the two fields above: the worker only ever reads this run row,
    # never a live per-request flag, so whatever was true when the run was created is what it acts on.
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False, default=RunStatus.QUEUED
    )
    # Cooperative cancellation flag - nodes check this at key points instead
    # of relying solely on Celery's revoke(terminate=True), which can't
    # interrupt a node already mid-flight or a WAITING_FOR_USER run that has
    # no active task to terminate at all.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    current_node: Mapped[str | None] = mapped_column(String, nullable=True)
    current_activity: Mapped[str | None] = mapped_column(String, nullable=True)

    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Free-form snapshots of LangGraph state that need to survive a worker
    # restart or a HITL pause - research plan/tasks, budget, pending human
    # action. Kept as JSONB rather than dedicated columns/tables at this
    # stage: their shape is still expected to move as the graph (Étape 4+)
    # is built out, and a schema migration per shape change would slow that
    # down for no benefit yet - promote a key to a real column/table once
    # its shape has actually stabilized.
    research_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pending_human_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.created_at"
    )


class RunEvent(UUIDMixin, TimestampMixin, Base):
    """One structured event per significant state change (§20 of the
    architecture brief) - the UI reconstructs real progress from these
    rather than a fabricated progress bar."""

    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    # Nullable: run-level events (run_started, run_completed, ...) aren't
    # correlated to a specific research task.
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")
