import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ExecutionMetric(UUIDMixin, TimestampMixin, Base):
    """What one execution cost the machine that ran it: how long it took, the CPU time it used and, for a
    worker task, the memory it held at most. Two kinds: a worker "task" (a Celery task - the whole run
    of the agent, the processing of a document...) and a "node" (a step of the agent's graph, inside a
    task). A node shares its process with the rest of the run, so it has no memory of its own: its
    time and CPU are a breakdown of the task's, never added to them.

    Same attribution as TokenUsage (UsageService.record_execution): run/document/collection ids kept as
    plain ids because consumption is history, user_id resolved from them once at record time."""

    __tablename__ = "execution_metrics"

    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # "task" or "node".
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # The worker task (summarize_document, run_agent...) or the graph node (analyze_query...).
    step: Mapped[str] = mapped_column(String, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpu_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Resident memory the task's process held at its highest; None for a node.
    peak_rss_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Shadows TimestampMixin's only to index it: every report filters on a period.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
