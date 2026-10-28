import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class DocumentTabularSheet(UUIDMixin, Base):
    """A sheet of a tabular file (#431): its analysis as the worker made it, and where its typed copy is.

    A workbook has several; a CSV, a JSON or a Parquet file has one. The profile of the document
    (`DocumentTabularProfile`) describes its main sheet in the shape Muffin has always had; this keeps them all, with
    every column's type, counts and statistics, and a few rows to look at. Replaced whole when the file is analysed
    again, dropped with the document - and so is its Parquet copy, whose key is kept here for that."""

    __tablename__ = "document_tabular_sheets"
    __table_args__ = (UniqueConstraint("document_id", "sheet_index", name="uq_document_tabular_sheets_document_index"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The sheet's place in the file, from 0 - the name its Parquet copy is given.
    index: Mapped[int] = mapped_column("sheet_index", Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Rows of data (the header is not one). A sheet longer than the analysis' bound is `truncated`.
    rows: Mapped[int] = mapped_column("row_count", Integer, nullable=False)
    header_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # [{index, name, type, non_null, null, type_counts, distinct, distinct_exact, sample_values, numeric?, text?,
    #   dates?, top_values?, error_cells?}, ...] - the analysis' own shape (docs/analyse-json.md of its source).
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # The first rows of data, as lists of cells.
    preview: Mapped[list[list[Any]]] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # {"rows": n, "columns": [{"name", "sql_type"}]} of the typed copy; None for a sheet with nothing to copy.
    table: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # RustFS key of the typed copy (Parquet), if any. Collected with the document's other objects when it is deleted.
    parquet_key: Mapped[str | None] = mapped_column(String, nullable=True)
