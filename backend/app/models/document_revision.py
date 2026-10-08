import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class RevisionOrigin(enum.StrEnum):
    UPLOAD = "upload"
    CHAT = "chat"
    UI = "ui"
    RESTORE = "restore"


class DocumentRevision(UUIDMixin, TimestampMixin, Base):
    """One version of a living document's file (#166). Append-only: replacing or restoring never
    rewrites an existing row, it adds a new revision - the current one is simply the highest
    number, and Document.storage_key is kept pointing at its file."""

    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "number", name="uq_document_revisions_document_number"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    # "odt" or "md" - derived from the filename extension at upload time, never changes across a
    # document's revisions.
    format: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[RevisionOrigin] = mapped_column(Enum(RevisionOrigin, name="revision_origin"), nullable=False)
    # Keycloak sub + a label resolved at write time, same convention as Document.added_by_*.
    created_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by_display: Mapped[str | None] = mapped_column(String, nullable=True)
    # Revision this one was restored from (origin=restore) - None otherwise.
    restored_from_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The agent run that produced it (origin=chat, later issues) - no FK: a revision must outlive
    # a purged run, and nothing here ever joins through it.
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    document: Mapped["Document"] = relationship(back_populates="revisions")  # noqa: F821
