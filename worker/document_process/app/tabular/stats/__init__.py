"""Package de stats descriptives tabulaires.

Re-exporte l'API publique pour préserver la compatibilité ascendante :
``from app.tabular.stats import compute_profile, TabularProfile, ...``
continue de fonctionner après la découpe en sous-modules.

Modules internes :
- ``models`` : dataclasses (ColumnStats, TabularProfile) + SemanticType + constantes ;
- ``types`` : prédicats de type physique (_is_numeric, _is_date, ...) + _safe_value ;
- ``classify`` : classification sémantique (_classify_column, _derive_classifications) ;
- ``fetchers`` : fonctions de récupération SQL (_fetch_*, _TYPE_STATS_FETCHERS) ;
- ``profile`` : orchestration (_column_stats, compute_profile).
"""

from __future__ import annotations

from app.tabular.stats.classify import classify_column, derive_classifications
from app.tabular.stats.fetchers import (
    TYPE_STATS_FETCHERS,
    fetch_base_counts,
    fetch_date_stats,
    fetch_numeric_stats,
    fetch_sample_rows,
    fetch_schema,
    fetch_text_stats,
    fetch_top_values,
)
from app.tabular.stats.models import (
    DIMENSION_CARDINALITY_RATIO,
    SAMPLE_ROWS_LIMIT,
    TEXT_AVG_LENGTH_THRESHOLD,
    TOP_VALUES_LIMIT,
    ColumnStats,
    SemanticType,
    TabularProfile,
)
from app.tabular.stats.profile import column_stats, compute_profile
from app.tabular.stats.types import (
    is_boolean,
    is_date,
    is_numeric,
    is_varchar,
    safe_value,
)

# ---------------------------------------------------------------------------
# Aliases avec préfixe ``_`` pour préserver la compatibilité avec les tests
# et le code existant qui importe ces noms privés.
# ---------------------------------------------------------------------------

_is_numeric = is_numeric
_is_date = is_date
_is_boolean = is_boolean
_is_varchar = is_varchar
_safe_value = safe_value
_classify_column = classify_column
_derive_classifications = derive_classifications
_column_stats = column_stats
_fetch_base_counts = fetch_base_counts
_fetch_top_values = fetch_top_values
_fetch_numeric_stats = fetch_numeric_stats
_fetch_date_stats = fetch_date_stats
_fetch_text_stats = fetch_text_stats
_fetch_schema = fetch_schema
_fetch_sample_rows = fetch_sample_rows
_TYPE_STATS_FETCHERS = TYPE_STATS_FETCHERS

__all__ = [
    # Modèles
    "ColumnStats",
    "TabularProfile",
    "SemanticType",
    # Constantes
    "TOP_VALUES_LIMIT",
    "SAMPLE_ROWS_LIMIT",
    "TEXT_AVG_LENGTH_THRESHOLD",
    "DIMENSION_CARDINALITY_RATIO",
    # Prédicats
    "is_numeric",
    "is_date",
    "is_boolean",
    "is_varchar",
    "safe_value",
    # Classification
    "classify_column",
    "derive_classifications",
    # Fetchers
    "fetch_base_counts",
    "fetch_top_values",
    "fetch_numeric_stats",
    "fetch_date_stats",
    "fetch_text_stats",
    "fetch_schema",
    "fetch_sample_rows",
    "TYPE_STATS_FETCHERS",
    # Profile
    "column_stats",
    "compute_profile",
    # Aliases privés (compatibilité)
    "_is_numeric",
    "_is_date",
    "_is_boolean",
    "_is_varchar",
    "_safe_value",
    "_classify_column",
    "_derive_classifications",
    "_column_stats",
    "_fetch_base_counts",
    "_fetch_top_values",
    "_fetch_numeric_stats",
    "_fetch_date_stats",
    "_fetch_text_stats",
    "_fetch_schema",
    "_fetch_sample_rows",
    "_TYPE_STATS_FETCHERS",
]
