import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class TaskStatus(enum.StrEnum):
    """Where a dispatched task is, persisted by the workers as they run it (see
    app/routers/internal_tasks.py's status endpoint). The values are Celery's own state names, so
    the API and the UI read the same strings they always did.

    UNKNOWN is only ever written by the migration that added this column: the tasks recorded
    before it have no status to recover, and must not read as still running."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


# A task still to run or running: the only ones worth revoking, and the only ones that make a
# collection's evaluation read as "in progress".
ACTIVE_TASK_STATUSES = frozenset({TaskStatus.PENDING, TaskStatus.STARTED})
# Over: the task will not change again (UNKNOWN is what the migration wrote for the rows that
# predate the status column).
TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCESS, TaskStatus.FAILURE, TaskStatus.REVOKED, TaskStatus.UNKNOWN})


class Task(UUIDMixin, TimestampMixin, Base):
    """A dispatched Celery task, recorded so a user can see its status and revoke it.

    The status is persisted here, written by the worker as the task starts and ends (see
    app/routers/internal_tasks.py's status endpoint and each worker's app/task_status.py) - not
    read from Celery's result backend, which cannot tell an id it no longer knows from one still
    waiting in the queue. A task whose worker died stays STARTED until the reaper marks it failed
    (see TaskRepository.reap_stuck). Its logs are lines of their own, sent while it runs: see
    app/models/task_log_entry.py (#305)."""

    __tablename__ = "tasks"

    celery_task_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String, nullable=False)
    # Keycloak subject (sub); who can see/revoke this task.
    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # All three nullable and independent: not every task type relates to a document/collection
    # (e.g. score_discussion - see #31 - relates to a conversation instead), and the referenced
    # row can outlive the task that created it either way.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    # e.g. chunk_document is a child of process_document, summarize_document
    # and the per-window qa/entity tasks are children of chunk_document - lets
    # the UI group a whole document's pipeline run under one card.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    # Set when the worker reports STARTED, refreshed on a retry/redelivery - the reaper reads
    # started_at to tell a task that is genuinely long from one whose worker is gone.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The exception a FAILURE ended on, as the worker reported it.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document | None"] = relationship()  # noqa: F821
    collection: Mapped["Collection | None"] = relationship()  # noqa: F821
    conversation: Mapped["Conversation | None"] = relationship()  # noqa: F821
    parent: Mapped["Task | None"] = relationship(remote_side="Task.id", back_populates="children")
    children: Mapped[list["Task"]] = relationship(back_populates="parent")

    @property
    def is_active(self) -> bool:
        """Still to run or running - what a revoke acts on, and what makes an evaluation read as
        in progress."""
        return self.status in ACTIVE_TASK_STATUSES
