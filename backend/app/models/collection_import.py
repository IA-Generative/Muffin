import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CollectionImportStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CollectionImport(UUIDMixin, TimestampMixin, Base):
    """A ZIP turned into a collection and its sub-collections (#223). The root collection is
    created right away, when the archive is uploaded; worker/document_process's import_zip then
    reads the archive, creates the sub-collections and documents through the internal API, and
    reports a summary here."""

    __tablename__ = "collection_imports"

    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # "Jean D." - stamped on every document the import creates, like a plain upload (§122).
    owner_display: Mapped[str] = mapped_column(String, nullable=False)
    archive_name: Mapped[str] = mapped_column(String, nullable=False)
    # Where the uploaded archive waits in RustFS until the import is done - deleted afterwards,
    # NULL from then on.
    archive_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[CollectionImportStatus] = mapped_column(
        Enum(CollectionImportStatus, name="collection_import_status"),
        nullable=False,
        default=CollectionImportStatus.PENDING,
    )
    # SET NULL, not CASCADE: the import record (and its summary) outlives a deleted collection.
    root_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The conversation the archive was dropped into, if any - its runs pin the imported collection
    # (see RunService.create_run). SET NULL: deleting the conversation never deletes what the user
    # imported, the collection stays.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # {"collections_created": int, "documents_created": int, "skipped": [{"path", "reason"}]}
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
