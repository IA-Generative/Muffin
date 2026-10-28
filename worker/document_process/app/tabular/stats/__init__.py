"""Package de stats descriptives tabulaires.

Re-exporte l'API publique pour préserver la compatibilité ascendante :
``from app.tabular.stats import compute_profile, TabularProfile, ...``
continue de fonctionner après la découpe en sous-modules.

Modules internes :
- ``models`` : dataclasses (ColumnStats, TabularProfile) + SemanticType + constantes ;
- ``types`` : prédicats de type physique (_is_numeric, _is_date, ...) + _safe_value ;
- ``classify`` : classification sémantique (_classify_column, _derive_classifications).

Les statistiques elles-mêmes ne sont plus calculées ici (par des requêtes DuckDB) mais par
``app.tabular.sheets``, qui lit le fichier en flux ; ``app.tabular.sheets.compat`` en tire ce profil.
"""

from __future__ import annotations

from app.tabular.stats.classify import classify_column, derive_classifications
from app.tabular.stats.models import (
    DIMENSION_CARDINALITY_RATIO,
    SAMPLE_ROWS_LIMIT,
    TEXT_AVG_LENGTH_THRESHOLD,
    TOP_VALUES_LIMIT,
    ColumnStats,
    SemanticType,
    TabularProfile,
)
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
    # Aliases privés (compatibilité)
    "_is_numeric",
    "_is_date",
    "_is_boolean",
    "_is_varchar",
    "_safe_value",
    "_classify_column",
    "_derive_classifications",
]
