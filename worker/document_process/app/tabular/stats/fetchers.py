"""Fonctions de récupération de statistiques depuis DuckDB.

Chaque fonction exécute une requête SQL agrégée sur une colonne donnée et
renvoie un résultat typé. Le dispatch ``TYPE_STATS_FETCHERS`` associe chaque
prédicat de type physique à la fonction de stats correspondante.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.tabular.stats.models import SAMPLE_ROWS_LIMIT, TOP_VALUES_LIMIT
from app.tabular.stats.types import is_date, is_numeric, is_varchar, safe_value


def fetch_base_counts(connection: Any, table_name: str, quoted: str) -> tuple[int, int, int]:
    """Compte total, non-null, distinct en une seule passe."""
    base = connection.execute(
        f"SELECT COUNT(*), COUNT({quoted}), COUNT(DISTINCT {quoted}) FROM {table_name}"
    ).fetchone()
    total_count, non_null_count, distinct_count = base
    return int(total_count), int(non_null_count), int(distinct_count)


def fetch_top_values(connection: Any, table_name: str, quoted: str) -> list[dict[str, Any]]:
    """Top N valeurs les plus fréquentes (fréquence décroissante)."""
    top = connection.execute(
        f"SELECT {quoted} AS value, COUNT(*) AS freq "
        f"FROM {table_name} WHERE {quoted} IS NOT NULL "
        f"GROUP BY {quoted} ORDER BY freq DESC LIMIT {TOP_VALUES_LIMIT}"
    ).fetchall()
    return [{"value": safe_value(v), "count": int(c)} for v, c in top]


def fetch_numeric_stats(connection: Any, table_name: str, quoted: str) -> dict[str, float | int | None] | None:
    """min, max, moyenne, médiane, écart-type pour une colonne numérique."""
    numeric = connection.execute(
        f"SELECT MIN({quoted}), MAX({quoted}), AVG({quoted}), "
        f"median({quoted}), stddev_samp({quoted}) FROM {table_name} WHERE {quoted} IS NOT NULL"
    ).fetchone()
    if not numeric or numeric[0] is None:
        return None
    return {
        "min": safe_value(numeric[0]),
        "max": safe_value(numeric[1]),
        "mean": safe_value(numeric[2]),
        "median": safe_value(numeric[3]),
        "stddev": safe_value(numeric[4]),
    }


def fetch_date_stats(connection: Any, table_name: str, quoted: str) -> dict[str, str | None] | None:
    """min/max pour une colonne temporelle (plage de dates)."""
    date_result = connection.execute(
        f"SELECT MIN({quoted}), MAX({quoted}) FROM {table_name} WHERE {quoted} IS NOT NULL"
    ).fetchone()
    if not date_result or date_result[0] is None:
        return None
    return {
        "min": safe_value(date_result[0]),
        "max": safe_value(date_result[1]),
    }


def fetch_text_stats(connection: Any, table_name: str, quoted: str) -> dict[str, int | float | None] | None:
    """Longueur min/max/moyenne pour une colonne VARCHAR."""
    text_result = connection.execute(
        f"SELECT MIN(length({quoted})), MAX(length({quoted})), "
        f"AVG(length({quoted})) FROM {table_name} WHERE {quoted} IS NOT NULL"
    ).fetchone()
    if not text_result or text_result[0] is None:
        return None
    return {
        "min_length": int(text_result[0]),
        "max_length": int(text_result[1]),
        "avg_length": (float(text_result[2]) if text_result[2] is not None else None),
    }


def fetch_schema(connection: Any, table_name: str) -> list[tuple[str, str]]:
    """Récupère le schéma de la table : liste de (nom, type DuckDB)."""
    schema = connection.execute(f"DESCRIBE {table_name}").fetchall()
    return [(row[0], row[1]) for row in schema]


def fetch_sample_rows(connection: Any, table_name: str, column_names: list[str]) -> list[dict[str, Any]]:
    """Récupère un échantillon de lignes pour le résumé LLM."""
    sample_rows_raw = connection.execute(f"SELECT * FROM {table_name} LIMIT {SAMPLE_ROWS_LIMIT}").fetchall()
    return [{col: safe_value(value) for col, value in zip(column_names, row, strict=False)} for row in sample_rows_raw]


# Dispatch : pour chaque type physique, la fonction qui récupère les stats
# spécifiques. ``None`` = pas de stats spécifiques pour ce type.
TYPE_STATS_FETCHERS: dict[
    Callable[[str], bool],
    Callable[[Any, str, str], dict[str, Any] | None],
] = {
    is_numeric: fetch_numeric_stats,
    is_date: fetch_date_stats,
    is_varchar: fetch_text_stats,
}
