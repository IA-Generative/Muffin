import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentType(enum.StrEnum):
    FILE = "file"
    URL = "url"


class DocumentKind(enum.StrEnum):
    STANDARD = "standard"
    # A "living" document (#166): an ODT or Markdown file whose content evolves through
    # revisions (replaced by upload today, edited through the chat later) instead of being
    # immutable once indexed. Same Document row, indexing and citations as any other file.
    LIVING = "living"


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
    # For a living document this always points at the current revision's file (see
    # DocumentRevision) - the worker keeps reading storage_key, it doesn't know about revisions.
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind"),
        nullable=False,
        default=DocumentKind.STANDARD,
        server_default=DocumentKind.STANDARD.name,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The stretches of pages the summary was made from, [[first, last], ...] (#372) - None when it read the whole
    # document, which is what a short document and a collection that does not sample long ones always get. A
    # summary that read a part says nothing of the rest: the research agent must not take it for the whole.
    summary_pages: Mapped[list[list[int]] | None] = mapped_column(JSONB, nullable=True)
    # Separate from summary: a summarize_document failure shouldn't be able to
    # clobber a real summary a previous run already produced, and vice versa.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SHA-256 of the file's bytes (#300): what tells that the same file is added twice, and what
    # another document reuses the results of. For a URL serving an HTML page there is no file to hash,
    # so it is the hash of the page's extracted text, lightly normalized (#19): the page's bytes change
    # at every read for reasons its content does not show (scripts, tokens, ads), and the scheduled
    # refresh only reprocesses the document when this hash differs. None until known: a file uploaded
    # before this existed gets it when it is next processed, and so does one whose file was replaced.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # A URL document (#19): when it was last fetched.
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft edit lock of a living document (#170) - all None when unlocked. An expired lock
    # (lock_expires_at in the past) counts as no lock at all, it is never swept: every check
    # compares against the current time. lock_token is returned only to the holder, who must
    # present it to write; the other lock_* columns are what everyone else sees.
    lock_token: Mapped[str | None] = mapped_column(String, nullable=True)
    locked_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    locked_by_display: Mapped[str | None] = mapped_column(String, nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    revisions: Mapped[list["DocumentRevision"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentRevision.number"
    )
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
    # One row per page: the worker writes a page with an upsert, so a task run twice (a redelivery after
    # a crash, #299) leaves the same pages instead of a second copy of each.
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # RustFS key of this page's PNG screenshot (liteparse-produced), if any -
    # scraped URL pages don't have one.
    screenshot: Mapped[str | None] = mapped_column(String, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="pages")
    text_boxes: Mapped[list["PageTextBox"]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="PageTextBox.position", lazy="noload"
    )
    regions: Mapped[list["PageRegion"]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="PageRegion.position", lazy="noload"
    )
    tables: Mapped[list["DocumentTable"]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="DocumentTable.rank", lazy="noload"
    )


class PageTextBox(UUIDMixin, Base):
    """A line of the page's text, with where it is (#350): its box, normalized between 0 and 1 against the page
    (so it lands on the screenshot whatever the scale it was rendered at), and its interval of characters in
    `DocumentPage.content` - NULL when the line could not be found in the content (OCR). `words` details its
    words with the same fields, so that a passage is framed word by word, not by the whole line. A table of its
    own: there are hundreds of lines per page, and they must not weigh on every query that lists the pages."""

    __tablename__ = "page_text_boxes"

    document_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Reading order within the page.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{"text", "x_min", "y_min", "x_max", "y_max", "char_start", "char_end"}, ...]
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    page: Mapped[DocumentPage] = relationship(back_populates="text_boxes")


class PageRegion(UUIDMixin, Base):
    """A region of the layout of a scanned page (#409): what the OCR pods found on it, kept so that it can be cropped,
    framed or described later without reading the page again. Its type (`text`, `title`, `table`, `image`, `formula`,
    `logo`, `stamp`, `header`, `footer`, `page_number`, ... - free text, a newer pod may have more), its score, and its
    box, normalized between 0 and 1 against the page (so it lands on the screenshot whatever the scale it was rendered
    at). Every region is here, the running headers and footers too - they are only left out of the page's content.
    No crop is stored: it is made from the page's image and this box when it is wanted. A table of its own, like
    `page_text_boxes`: replaced with the page, dropped with it."""

    __tablename__ = "page_regions"

    document_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Reading order within the page, from 0.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    # [[x, y], ...] between 0 and 1 - the outline, when the model gave one.
    polygon: Mapped[list[list[float]] | None] = mapped_column(JSONB, nullable=True)
    # A title only: 1 for the document's, 2 for a section's.
    title_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The description of an image or a table (#411), and the model that wrote it. NULL: not described.
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The table read from this region (#410), when it is one and was read. Dropped (not the region) with its table.
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_tables.id", ondelete="SET NULL", name="fk_page_regions_table_id"), nullable=True
    )

    page: Mapped[DocumentPage] = relationship(back_populates="regions")


class DocumentTable(UUIDMixin, Base):
    """A table read on a scanned page (#410): what the agent goes to read when a passage says a table is there, its
    content being kept out of the chunks. Identified within its document by its page and its `rank` on the page (1 for
    the first in reading order) - which is what the page's text says (`[Tableau <document>/p3/t1 ...]`), and does not
    change when the page is read again. Replaced with the page, dropped with it - like the layout it was read from.

    `cells` is the grid: `[{"row", "col", "row_span", "col_span", "text"}, ...]`, rows and columns from 0; `markdown`
    and `html` are that grid written out (HTML when a cell spans several - Markdown cannot say it). `reliable` is False
    when the structure is doubtful: the content is there, it is just not to be trusted blindly."""

    __tablename__ = "document_tables"
    __table_args__ = (UniqueConstraint("document_page_id", "rank", name="uq_document_tables_page_rank"),)

    document_page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The first row's texts, when it is a header.
    headers: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    cells: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    page: Mapped[DocumentPage] = relationship(back_populates="tables")
