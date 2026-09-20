"""Orchestration du profilage tabulaire.

``_column_stats`` assemble les stats d'une colonne (base + spécifiques au
type + classification sémantique). ``compute_profile`` est le point
d'entrée public qui profile une table complète : schéma, stats par colonne,
classifications dérivées, et lignes d'échantillon.
"""

from __future__ import annotations

from typing import Any

from app.tabular.loader import LoadedTable
from app.tabular.stats.classify import classify_column, derive_classifications
from app.tabular.stats.fetchers import (
    TYPE_STATS_FETCHERS,
    fetch_base_counts,
    fetch_sample_rows,
    fetch_schema,
    fetch_top_values,
)
from app.tabular.stats.models import ColumnStats, TabularProfile
from app.tabular.stats.types import is_date, is_numeric, is_varchar


def _quote_identifier(name: str) -> str:
    """Quote un identifiant SQL pour éviter les injections/collisions avec
    mots-clés réservés. DuckDB utilise les double-quotes."""
    return f'"{name}"'


def column_stats(
    connection: Any,
    table_name: str,
    column_name: str,
    column_type: str,
    row_count: int,
) -> ColumnStats:
    """Calcule les stats complètes d'une colonne.

    1. Compte total / non-null / distinct ;
    2. Récupère les top valeurs (pour les catégorielles) ;
    3. Récupère les stats spécifiques au type (numérique / date / texte) ;
    4. Classifie la colonne en type sémantique.
    """
    quoted = _quote_identifier(column_name)

    total_count, non_null_count, distinct_count = fetch_base_counts(connection, table_name, quoted)
    null_count = total_count - non_null_count

    # Top valeurs : toujours récupérées (limitées à TOP_VALUES_LIMIT).
    top_values = fetch_top_values(connection, table_name, quoted)

    # Stats spécifiques au type : on dispatch selon le type physique.
    type_specific_stats: dict[str, Any] | None = None
    for predicate, fetcher in TYPE_STATS_FETCHERS.items():
        if predicate(column_type):
            type_specific_stats = fetcher(connection, table_name, quoted)
            break

    # Classification sémantique.
    text_stats = type_specific_stats if is_varchar(column_type) else None
    semantic_type = classify_column(column_type, distinct_count, row_count, text_stats)

    # Attribue le bon attribut selon le type sémantique.
    numeric_stats = type_specific_stats if is_numeric(column_type) else None
    date_stats = type_specific_stats if is_date(column_type) else None

    return ColumnStats(
        name=column_name,
        type=column_type,
        semantic_type=semantic_type,
        null_count=null_count,
        distinct_count=distinct_count,
        top_values=top_values,
        numeric_stats=numeric_stats,
        date_stats=date_stats,
        text_stats=text_stats,
    )


def compute_profile(table: LoadedTable) -> TabularProfile:
    """Profile une table DuckDB : stats par colonne + classifications.

    Args:
        table: table chargée en mémoire (connexion + nom + format).

    Returns:
        TabularProfile complet avec stats par colonne, classifications
        (measures/dimensions/text_columns), et lignes d'échantillon.
    """
    connection = table.connection
    table_name = table.table_name

    # 1. Schéma : liste de (nom, type).
    schema = fetch_schema(connection, table_name)
    columns_info = schema

    # 2. Compte total de lignes (pour les ratios de cardinalité).
    row_count = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    # 3. Stats par colonne.
    columns: list[ColumnStats] = []
    for col_name, col_type in columns_info:
        col_stats = column_stats(connection, table_name, col_name, col_type, row_count)
        columns.append(col_stats)

    # 4. Classifications dérivées.
    measures, dimensions, text_columns = derive_classifications(columns)

    # 5. Lignes d'échantillon pour le résumé LLM.
    column_names = [c[0] for c in columns_info]
    sample_rows = fetch_sample_rows(connection, table_name, column_names)

    return TabularProfile(
        row_count=row_count,
        column_count=len(columns_info),
        columns=columns,
        sample_rows=sample_rows,
        format=table.format.value,
        measures=measures,
        dimensions=dimensions,
        text_columns=text_columns,
    )
