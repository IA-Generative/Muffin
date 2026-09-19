import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Task(UUIDMixin, TimestampMixin, Base):
    """A dispatched Celery task, recorded so a user can see its status and
    revoke it. Live status isn't stored here - it's looked up from Celery's
    own result backend by celery_task_id (see app/core/tasks.py), so there's
    nothing to keep in sync. Logs are stored here though: Celery's result
    backend only keeps the return value/exception, not the loguru output the
    worker produced along the way, and the user wants that raw output
    available for every task, not just failed ones."""

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
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document | None"] = relationship()  # noqa: F821
    collection: Mapped["Collection | None"] = relationship()  # noqa: F821
    conversation: Mapped["Conversation | None"] = relationship()  # noqa: F821
    parent: Mapped["Task | None"] = relationship(remote_side="Task.id", back_populates="children")
    children: Mapped[list["Task"]] = relationship(back_populates="parent")
