import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaskLogEntry(Base):
    """One line a worker logged while running a Celery task (#305), sent a few at a time while the task
    runs - so its logs can be followed live, and are kept even when the pod dies halfway through.

    Keyed by the Celery task id, not a foreign key to `tasks`: a task the beat sends (the URL refresh
    scan) has no Task row and logs all the same. The document and the collection are copied on every
    line, so that a whole document's pipeline reads as one timeline, whichever task each line came from.
    Purged after TASK_LOG_RETENTION_DAYS (see DELETE /internal/task-logs)."""

    __tablename__ = "task_log_entries"
    __table_args__ = (
        Index("ix_task_log_entries_task", "celery_task_id", "id"),
        Index("ix_task_log_entries_document", "document_id", "id"),
        Index("ix_task_log_entries_ts", "ts"),
    )

    # Increasing: the cursor a reader passes back (`after`) to get only the lines it has not seen.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    celery_task_id: Mapped[str] = mapped_column(String, nullable=False)
    task_name: Mapped[str] = mapped_column(String, nullable=False)
    # No foreign keys: a line goes with the retention, not with its document.
    document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    # With the traceback, when the line was logged with an exception.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Where it was logged from: module, function, line.
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
