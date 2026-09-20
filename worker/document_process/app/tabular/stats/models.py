"""Modèles de données et constantes pour les stats tabulaires.

Définit les dataclasses ``ColumnStats`` et ``TabularProfile``, la classe
``SemanticType`` (types sémantiques de colonnes), et les constantes de
configuration (seuils de classification, limites d'échantillonnage).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Nombre de valeurs d'exemple à garder pour les colonnes catégorielles.
TOP_VALUES_LIMIT = 5
# Nombre de lignes d'échantillon à renvoyer pour le résumé LLM.
SAMPLE_ROWS_LIMIT = 5
# Seuil de longueur moyenne au-dessus duquel une colonne VARCHAR est
# considérée comme "texte libre" (nécessite chunking + embeddings).
TEXT_AVG_LENGTH_THRESHOLD = 200
# Ratio de cardinalité en dessous duquel une colonne est une dimension
# plutôt qu'une measure (ex. 50% des lignes = catégorielle).
DIMENSION_CARDINALITY_RATIO = 0.5

# Types DuckDB considérés comme numériques pour les stats min/max/mean.
# BIGINT, INTEGER, SMALLINT, TINYINT, HUGEINT, FLOAT, DOUBLE, DECIMAL, REAL.
_NUMERIC_PREFIXES = (
    "BIGINT",
    "INTEGER",
    "SMALLINT",
    "TINYINT",
    "HUGEINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
    "INT",
)

# Types DuckDB considérés comme dates/temporels.
_DATE_PREFIXES = ("DATE", "TIMESTAMP", "TIME")


class SemanticType:
    """Type sémantique d'une colonne, déduit des stats.

    Values: ``measure``, ``dimension``, ``datetime``, ``text``,
    ``identifier``, ``boolean``, ``other``.
    """

    MEASURE = "measure"
    DIMENSION = "dimension"
    DATETIME = "datetime"
    TEXT = "text"
    IDENTIFIER = "identifier"
    BOOLEAN = "boolean"
    OTHER = "other"


@dataclass
class ColumnStats:
    name: str
    type: str
    semantic_type: str = "other"
    null_count: int = 0
    distinct_count: int = 0
    # Top valeurs pour les colonnes catégorielles (fréquence décroissante).
    top_values: list[dict[str, Any]] = field(default_factory=list)
    # Stats numériques (None pour les colonnes non numériques).
    numeric_stats: dict[str, float | int | None] | None = None
    # Stats de dates : min/max (None pour les colonnes non temporelles).
    date_stats: dict[str, str | None] | None = None
    # Stats texte : longueur min/max/moyenne (None pour les non-VARCHAR).
    text_stats: dict[str, int | float | None] | None = None


@dataclass
class TabularProfile:
    row_count: int
    column_count: int
    columns: list[ColumnStats]
    sample_rows: list[dict[str, Any]]
    format: str
    # Classification dérivée des ColumnStats.semantic_type.
    measures: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [asdict(col) for col in self.columns],
            "sample_rows": self.sample_rows,
            "format": self.format,
            "measures": self.measures,
            "dimensions": self.dimensions,
            "text_columns": self.text_columns,
        }
