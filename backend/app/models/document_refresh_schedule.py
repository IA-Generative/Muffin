import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# What a URL document can be refreshed every - multiples of how often the scan runs (every 30
# minutes, see worker/document_process's beat schedule): anything shorter couldn't be honoured.
REFRESH_INTERVALS_MINUTES = (30, 60, 360, 720, 1440, 10080)


class DocumentRefreshSchedule(UUIDMixin, TimestampMixin, Base):
    """How often a URL document is fetched again (#19). A periodic scan claims the schedules that
    are due, moves each one's next_run_at forward, and has the page fetched: if its content changed
    (DocumentRefreshService.report_fetch compares the hash), the document is reprocessed from
    scratch - summary, chunks, embeddings, QA, entities, tags all replaced. One per document at most;
    no row means no automatic refresh."""

    __tablename__ = "document_refresh_schedules"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    document: Mapped["Document"] = relationship()  # noqa: F821
