import enum
import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.routine_schedule import DEFAULT_TIMEZONE, RoutineKind
from app.models.base import Base, TimestampMixin, UUIDMixin


class RoutineCondition(enum.StrEnum):
    ALWAYS = "always"
    # The agent is not started - nothing is spent - when no document of the collections was added or changed since the
    # last check.
    ONLY_IF_NEW = "only_if_new"


class RoutineResultMode(enum.StrEnum):
    # Each run makes a conversation of its own.
    NEW_CONVERSATION = "new_conversation"
    # Every run goes on in one conversation per routine.
    SINGLE_CONVERSATION = "single_conversation"


class RoutineNotify(enum.StrEnum):
    ALWAYS = "always"
    FAILURE = "failure"
    NEVER = "never"


class RoutineState(enum.StrEnum):
    ACTIVE = "active"
    # By the person.
    PAUSED = "paused"
    # By the system or an administrator: `suspended_reason` says why. The person resumes it, unless an administrator
    # did.
    SUSPENDED = "suspended"


class RoutineRunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Routine(UUIDMixin, TimestampMixin, Base):
    """A question asked of the agent at a regular rhythm, by the person themselves, without their opening the chat
    (#524). It runs in the background with the person's rights as they are at each run, never as an administrator, and
    with none of the tools that need the person's token: it searches the collections, and the web if allowed. Each run
    makes (or continues) a conversation the person can open and carry on."""

    __tablename__ = "routines"

    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    owner_display: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    collection_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    include_descendants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True
    )
    web_search: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    kind: Mapped[RoutineKind] = mapped_column(Enum(RoutineKind, name="routine_kind"), nullable=False)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[time | None] = mapped_column(nullable=True)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)

    condition: Mapped[RoutineCondition] = mapped_column(
        Enum(RoutineCondition, name="routine_condition"), nullable=False, default=RoutineCondition.ALWAYS
    )
    result_mode: Mapped[RoutineResultMode] = mapped_column(
        Enum(RoutineResultMode, name="routine_result_mode"), nullable=False, default=RoutineResultMode.NEW_CONVERSATION
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    notify: Mapped[RoutineNotify] = mapped_column(
        Enum(RoutineNotify, name="routine_notify"), nullable=False, default=RoutineNotify.ALWAYS
    )

    state: Mapped[RoutineState] = mapped_column(
        Enum(RoutineState, name="routine_state"), nullable=False, default=RoutineState.ACTIVE, index=True
    )
    # `failures`, `inactive`, `admin`: why the system put it aside.
    suspended_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Only an active routine has a next date; a sweep takes the ones that are due.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Up to when the documents were looked at for "only if there is something new": the last run, skipped or not.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class RoutineRun(UUIDMixin, Base):
    """One run of a routine, or the reason it was not made: the history the person reads. `run_id` and
    `conversation_id` are plain ids - the history outlives a conversation the person deleted."""

    __tablename__ = "routine_runs"

    routine_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("routines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[RoutineRunStatus] = mapped_column(Enum(RoutineRunStatus, name="routine_run_status"), nullable=False)
    # `no_new_documents`, `previous_running`, `access_lost`, `daily_limit`, `function_off`: why nothing was asked.
    skip_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # `schedule` or `manual`.
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="schedule")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # What the person should know of a run that went through: a collection that was no longer theirs and was left out.
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoutineSettings(Base):
    """The limits of the routines for the whole application (#524): one row (id is always 1), admin-only, **off by
    default** - a routine spends model calls with nobody at the screen."""

    __tablename__ = "routine_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    max_active_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    max_runs_per_user_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    max_consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    inactive_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    run_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
