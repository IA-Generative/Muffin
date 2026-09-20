"""Prédicats de type physique DuckDB et utilitaire de sérialisation.

Ces fonctions testent le type physique d'une colonne DuckDB (renvoyé par
``DESCRIBE``) pour déterminer sa catégorie : numérique, temporel, booléen,
ou texte. ``_safe_value`` convertit les valeurs DuckDB non-primitives
(Decimal, datetime, etc.) en types JSON-sérialisables.
"""

from __future__ import annotations

from typing import Any

from app.tabular.stats.models import _DATE_PREFIXES, _NUMERIC_PREFIXES


def is_numeric(duckdb_type: str) -> bool:
    return duckdb_type.upper().startswith(_NUMERIC_PREFIXES)


def is_date(duckdb_type: str) -> bool:
    return duckdb_type.upper().startswith(_DATE_PREFIXES)


def is_boolean(duckdb_type: str) -> bool:
    return duckdb_type.upper() == "BOOLEAN"


def is_varchar(duckdb_type: str) -> bool:
    return duckdb_type.upper().startswith("VARCHAR") or duckdb_type.upper().startswith("CHAR")


def safe_value(value: Any) -> Any:
    """Convertit une valeur DuckDB en quelque chose de sérialisable en JSON.
    DuckDB renvoie des Decimal pour DECIMAL, des datetime pour TIMESTAMP,
    etc. - on stringify tout ce qui n'est pas un type primitif."""
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)
