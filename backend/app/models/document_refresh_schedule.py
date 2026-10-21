import enum
import uuid
from datetime import datetime, time

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, SmallInteger, String, Time
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

# How often the scan looks for documents due: on the hour and at half past (see
# worker/document_process's beat schedule). Every time and interval a schedule takes is on that grid,
# anything finer couldn't be honoured.
SCAN_MINUTES = 30
# The longest interval offered: one week.
MAX_INTERVAL_MINUTES = 7 * 24 * 60
DEFAULT_TIMEZONE = "Europe/Paris"


class RefreshKind(enum.StrEnum):
    # A single fetch at a date and time (next_run_at); the schedule goes away once it ran.
    ONCE = "once"
    # Every day at time_of_day.
    DAILY = "daily"
    # On each of weekdays (0 = Monday) at time_of_day.
    WEEKLY = "weekly"
    # Every interval_minutes, counted from the first run.
    INTERVAL = "interval"


class DocumentRefreshSchedule(UUIDMixin, TimestampMixin, Base):
    """When a URL document is fetched again (#19). A periodic scan claims the schedules that are due,
    moves each one's next_run_at forward (or, for a single fetch, removes it), and has the page
    fetched: if its content changed (DocumentRefreshService.report_fetch compares the hash), the
    document is reprocessed from scratch - summary, chunks, embeddings, QA, entities, tags all
    replaced. One per document at most; no row means no automatic refresh."""

    __tablename__ = "document_refresh_schedules"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    kind: Mapped[RefreshKind] = mapped_column(Enum(RefreshKind, name="refresh_kind"), nullable=False)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[time | None] = mapped_column(Time, nullable=True)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)
    # The times of day are the owner's wall-clock times: the next run is computed in this zone, so
    # "every day at 9:00" stays at 9:00 across daylight saving changes.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    document: Mapped["Document"] = relationship()  # noqa: F821
