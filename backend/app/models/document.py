import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentType(enum.StrEnum):
    FILE = "file"
    URL = "url"


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    ERROR = "error"


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # For type=url, name doubles as the URL to fetch. For type=file, the raw
    # bytes live in RustFS under storage_key - name is just the display name.
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType, name="document_type"), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Separate from summary: a summarize_document failure shouldn't be able to
    # clobber a real summary a previous run already produced, and vice versa.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who uploaded this document (§122) - the Keycloak sub, for an eventual "my files" filter,
    # and a label already resolved at upload time (e.g. "Jean D.") rather than the raw sub, which
    # is meaningless in the UI and never resolved anywhere else in this codebase either (see
    # Collection.description_updated_by). Both None for a document created before this existed.
    added_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    added_by_display: Mapped[str | None] = mapped_column(String, nullable=True)

    # Filing suggestion (§122/§124): set once a file uploaded straight into a conversation has
    # been summarized, by comparing its summary embedding to every collection description the
    # uploader owns. SET NULL (not CASCADE) if the suggested collection is later deleted - the
    # suggestion itself becomes moot, but the document and its other fields must survive that.
    suggested_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )
    suggested_collection_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Top-K candidates behind suggested_collection_id/score above (which is just candidates[0]) -
    # [{"collection_id": str, "collection_name": str, "collection_description": str, "score":
    # float}, ...], denormalized rather than a join table: it's a point-in-time snapshot of a
    # suggestion (§122 quality metrics want "what was predicted" preserved even if the candidate
    # collection is later renamed, redescribed or deleted), not a live relationship.
    filing_candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # The user chose "Ne rien faire" (§122) - suppresses the chat notification for this file
    # without moving it, and without the next suggestion computation re-nagging about it. Never
    # reset automatically; only a fresh upload starts unset again.
    filing_dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    collection: Mapped["Collection"] = relationship(back_populates="documents", foreign_keys=[collection_id])  # noqa: F821
    suggested_collection: Mapped["Collection | None"] = relationship(  # noqa: F821
        foreign_keys=[suggested_collection_id]
    )
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
    )
    chunks: Mapped[list["Chunk"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan", order_by="Chunk.index"
    )
    tags: Mapped[list["DocumentTag"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    tabular_profile: Mapped["DocumentTabularProfile | None"] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)

    document: Mapped["Document"] = relationship(back_populates="tags")


class DocumentPage(UUIDMixin, Base):
    """Raw textual content extracted from a single page of a document."""

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # RustFS key of this page's PNG screenshot (liteparse-produced), if any -
    # scraped URL pages don't have one.
    screenshot: Mapped[str | None] = mapped_column(String, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="pages")
