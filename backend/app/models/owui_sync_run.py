import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OwuiSyncRun(TimestampMixin, Base):
    """One synchronisation with Open WebUI (#466), as its worker reports it: started, then done with its account - or
    failed. The worker's own result expires with Celery's after a week and nothing else reads it, so the account is
    kept here for the administrators' page. Only the latest few are kept."""

    __tablename__ = "owui_sync_runs"

    # The id the worker gave the run: what it reports again when it ends.
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    # "running", "done" (the account tells what went wrong in it, if anything) or "failed" (it could not even start).
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What finish_sync gives: groups, knowledge bases and files seen, in error, dropped.
    account: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
