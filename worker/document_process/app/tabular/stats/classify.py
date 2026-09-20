"""Classification sémantique des colonnes.

Déduit le type sémantique d'une colonne (measure, dimension, datetime, text,
identifier, boolean, other) à partir de son type physique DuckDB et de ses
statistiques. Regroupe aussi les colonnes par type sémantique pour produire
les listes ``measures``, ``dimensions``, ``text_columns`` du profil.
"""

from __future__ import annotations

from app.tabular.stats.models import (
    DIMENSION_CARDINALITY_RATIO,
    TEXT_AVG_LENGTH_THRESHOLD,
    ColumnStats,
    SemanticType,
)
from app.tabular.stats.types import is_boolean, is_date, is_numeric, is_varchar


def classify_column(
    column_type: str,
    distinct_count: int,
    row_count: int,
    text_stats: dict[str, int | float | None] | None,
) -> str:
    """Déduit le type sémantique d'une colonne à partir de son type physique
    et de ses statistiques.

    Règles (par ordre de priorité) :
    1. BOOLEAN → ``boolean`` ;
    2. DATE/TIMESTAMP → ``datetime`` ;
    3. Cardinalité = nb de lignes (et > 1) → ``identifier`` ;
    4. Numérique avec cardinalité élevée → ``measure`` ;
    5. VARCHAR avec longueur moyenne élevée → ``text`` ;
    6. Sinon → ``dimension`` (catégorielle par défaut).
    """
    if is_boolean(column_type):
        return SemanticType.BOOLEAN
    if is_date(column_type):
        return SemanticType.DATETIME

    if row_count > 0 and distinct_count == row_count and distinct_count > 1:
        return SemanticType.IDENTIFIER

    if is_numeric(column_type):
        # Une measure est continue : cardinalité élevée par rapport au nb de
        # lignes. En dessous du seuil, c'est plutôt une dimension ordinale.
        ratio = distinct_count / row_count if row_count > 0 else 1.0
        if ratio >= DIMENSION_CARDINALITY_RATIO:
            return SemanticType.MEASURE
        return SemanticType.DIMENSION

    if is_varchar(column_type):
        if text_stats and text_stats.get("avg_length") is not None:
            if text_stats["avg_length"] >= TEXT_AVG_LENGTH_THRESHOLD:
                return SemanticType.TEXT
        return SemanticType.DIMENSION

    return SemanticType.OTHER


def derive_classifications(
    columns: list[ColumnStats],
) -> tuple[list[str], list[str], list[str]]:
    """Regroupe les noms de colonnes par type sémantique.

    Returns: (measures, dimensions, text_columns).
    """
    measures = [c.name for c in columns if c.semantic_type == SemanticType.MEASURE]
    dimensions = [c.name for c in columns if c.semantic_type in (SemanticType.DIMENSION, SemanticType.BOOLEAN)]
    text_columns = [c.name for c in columns if c.semantic_type == SemanticType.TEXT]
    return measures, dimensions, text_columns
