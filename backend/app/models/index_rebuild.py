import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class IndexRebuildStatus(enum.StrEnum):
    # The new index is being built next to the active one, which keeps serving every search.
    BUILDING = "building"
    # The new index has replaced the old one, atomically; the old one is kept until the owner
    # validates the switch (it is then deleted) or rolls back to it.
    SWAPPED = "swapped"
    FINALIZED = "finalized"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


# A collection has at most one rebuild in these states: it holds the collection's second index.
ACTIVE_REBUILD_STATUSES = (IndexRebuildStatus.BUILDING, IndexRebuildStatus.SWAPPED)


class IndexRebuild(UUIDMixin, TimestampMixin, Base):
    """A blue/green rebuild of a collection's search index (#12), for a change of embedding model:
    every vector is computed again with the new model into a second index while the active one keeps
    answering, then the two are swapped in one atomic step. Nothing is reprocessed - the chunks,
    summaries and QA pairs in PostgreSQL stay as they are, only their vectors are redone.

    The progress lives here, not in the worker: the build is a reconciliation of the new index against
    PostgreSQL, so a crashed or restarted job simply picks up what is still missing."""

    __tablename__ = "index_rebuilds"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[IndexRebuildStatus] = mapped_column(
        Enum(IndexRebuildStatus, name="index_rebuild_status"), nullable=False
    )
    # The model the new index is built with, and the one the active index had - what a rollback
    # returns to.
    target_model: Mapped[str] = mapped_column(String, nullable=False)
    previous_model: Mapped[str] = mapped_column(String, nullable=False)
    # Points (chunks, summaries, QA questions) the index must hold, and how many it already does.
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    swapped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The per-collection lock, in the database too: a second rebuild can't start while one is
        # building or awaiting validation (it would need the same second index).
        Index(
            "uq_index_rebuilds_one_active",
            "collection_id",
            unique=True,
            postgresql_where=text("status IN ('BUILDING', 'SWAPPED')"),
        ),
    )
