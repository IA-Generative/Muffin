import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentTabularProfile(UUIDMixin, TimestampMixin, Base):
    """Profil statistique d'un document tabulaire (CSV/TSV/PSV/XLSX/XLS/ODS/JSON/JSONL/Parquet),
    calculé par le worker document_process.

    One-to-one avec Document : un document non tabulaire n'a pas de profil.
    Le profil est un JSONB contenant le schéma, les stats par colonne et
    un échantillon de lignes - voir issue #69. Il décrit la feuille principale du fichier (celle qui a le plus de
    lignes) ; toutes les feuilles sont dans `document_tabular_sheets` (#431).
    """

    __tablename__ = "document_tabular_profiles"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Format source : "csv" | "tsv" | "psv" | "parquet" | "json" | "jsonl" | "xlsx" | "xls" | "ods"
    format: Mapped[str] = mapped_column(String, nullable=False)
    # [{name, type, semantic_type, null_count, distinct_count, top_values,
    #   numeric_stats, date_stats, text_stats}, ...]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # Échantillon de lignes (limité à 5 par le worker) pour le frontend et le debug.
    sample_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # Classification dérivée : noms de colonnes numériques continues.
    measures: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Classification dérivée : noms de colonnes catégorielles.
    dimensions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Colonnes contenant du texte libre (nécessitent chunking + embeddings).
    text_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Of the shape of `document_tabular_sheets` the worker sent with it (#431). NULL: a profile computed before the
    # sheets were kept (by DuckDB, on the first sheet only), which has none - re-indexing the document gives it some.
    analysis_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped["Document"] = relationship(  # noqa: F821
        back_populates="tabular_profile"
    )
