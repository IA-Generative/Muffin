"""Chargement de fichiers tabulaires dans DuckDB.

DuckDB tourne in-process dans le worker. La connexion est créée pour la durée
d'une tâche et fermée immédiatement après - aucune persistance, aucun serveur.

Lecture directe S3 :
- DuckDB lit directement depuis RustFS/S3 via l'extension ``httpfs`` (pas de
  ``get_object`` préalable, pas de fichier temporaire).
- XLSX : lu via l'extension ``spatial`` de DuckDB (GDAL), également depuis S3.

DuckDB gère son propre buffer pool : au-delà de ``DUCKDB_MEMORY_LIMIT``, il
 déverse sur disque (spill) plutôt que de faire grossir le RSS du worker.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import duckdb

from app.config import settings
from app.tabular.detect import TabularFormat

# Nom de la table DuckDB par défaut dans laquelle le fichier est chargé.
# En pratique, ``load_tabular`` génère un nom basé sur le document_id.
TABLE_NAME = "source"

# Limite mémoire appliquée à DuckDB en mode low-memory. DuckDB gère son
# propre buffer pool : au-delà de cette limite, il déverse sur disque
# (spill) plutôt que de faire grossir le RSS du worker. 2 Go est un compromis
# pour un worker qui peut traiter plusieurs documents en parallèle.
DUCKDB_MEMORY_LIMIT = "2GB"
# Nombre de threads DuckDB. Limité à 2 pour éviter qu'un worker ne sature
# tous les cœurs disponibles (le worker a d'autres tâches en parallèle).
DUCKDB_THREADS = 2


@dataclass
class LoadedTable:
    """Table DuckDB chargée temporairement. `connection` est valide tant que
    le context manager `load_tabular` est actif - ne pas retenir la connexion
    au-delà."""

    connection: duckdb.DuckDBPyConnection
    format: TabularFormat
    table_name: str = TABLE_NAME


def _duckdb_kwargs(format: TabularFormat) -> dict[str, object]:
    """Options de read_csv_auto / read_json_auto adaptées au format.

    `read_csv_auto` est robuste par défaut (sniff du délimiteur, inférence
    des types), mais on force `header=true` pour les formats où l'extension
    est explicite - un CSV sans en-tête est rare en pratique et l'inférence
    auto de DuckDB se trompe souvent dans ce cas."""
    if format in (TabularFormat.CSV, TabularFormat.TSV, TabularFormat.PSV):
        return {"header": True, "ignore_errors": False, "all_varchar": False}
    return {}


def _s3_url(storage_key: str) -> str:
    """Construit l'URL S3 que DuckDB httpfs peut lire directement.

    RustFS est S3-compatible : ``s3://<bucket>/<key>`` fonctionne avec
    l'extension ``httpfs`` de DuckDB, à condition d'avoir configuré les
    credentials via ``SET s3_access_key_id`` / ``SET s3_secret_access_key``.
    """
    return f"s3://{settings.RUSTFS_BUCKET}/{storage_key}"


def _load_statement(format: TabularFormat, source: str, table_name: str) -> str:
    """Construit la requête SQL qui charge le fichier dans la table DuckDB.

    ``source`` peut être un chemin local ou une URL S3 (``s3://...``) -
    DuckDB gère les deux via ``read_csv_auto`` / ``read_parquet`` / ``read_json_auto``.
    Pour le XLSX, on utilise l'extension ``spatial`` de DuckDB qui sait lire
    les fichiers Excel directement (y compris depuis S3).
    ``table_name`` est le nom de la table DuckDB créée (utilise le document_id
    pour éviter les collisions si plusieurs tables coexistent).
    """
    kwargs = _duckdb_kwargs(format)
    options = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    options_str = f", {options}" if options else ""

    if format in (TabularFormat.CSV, TabularFormat.TSV, TabularFormat.PSV):
        # read_csv_auto sniff le délimiteur, mais on force le nôtre quand
        # l'extension est explicite (TSV -> tab, PSV -> pipe).
        delimiter = {
            TabularFormat.TSV: "\\t",
            TabularFormat.PSV: "|",
            TabularFormat.CSV: ",",
        }[format]
        return f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{source}', delim='{delimiter}'{options_str})"
    if format == TabularFormat.PARQUET:
        return f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{source}')"
    if format in (TabularFormat.JSON, TabularFormat.JSONL):
        return f"CREATE TABLE {table_name} AS SELECT * FROM read_json_auto('{source}'{options_str})"
    if format == TabularFormat.XLSX:
        # L'extension spatial de DuckDB sait lire le XLSX directement,
        # y compris depuis S3. ``st_read`` est le point d'entrée ; on ne
        # garde que la première feuille (layer 0) pour P0.
        return f"CREATE TABLE {table_name} AS SELECT * FROM st_read('{source}', layer=0)"
    raise ValueError(f"Unsupported tabular format for DuckDB loading: {format}")


def _configure_s3(connection: duckdb.DuckDBPyConnection) -> None:
    """Configure l'extension httpfs de DuckDB pour lire/écrire sur RustFS.

    DuckDB peut lire directement depuis S3 sans passer par boto3 : il suffit
    d'installer l'extension ``httpfs`` et de configurer les credentials.
    RustFS étant S3-compatible, on pointe vers son endpoint.
    """
    connection.execute("INSTALL httpfs")
    connection.execute("LOAD httpfs")
    connection.execute(
        f"SET s3_endpoint='{settings.RUSTFS_ENDPOINT_URL.replace('http://', '').replace('https://', '')}'"
    )
    connection.execute(f"SET s3_access_key_id='{settings.RUSTFS_ACCESS_KEY}'")
    connection.execute(f"SET s3_secret_access_key='{settings.RUSTFS_SECRET_KEY}'")
    connection.execute("SET s3_url_style='path'")


def _configure_spatial(connection: duckdb.DuckDBPyConnection) -> None:
    """Installe l'extension ``spatial`` de DuckDB, nécessaire pour lire le
    XLSX via ``st_read``. L'extension ``spatial`` embarque GDAL qui sait
    décoder le format Excel (entre autres)."""
    connection.execute("INSTALL spatial")
    connection.execute("LOAD spatial")


@contextmanager
def load_tabular(storage_key: str, format: TabularFormat, document_id: str) -> Iterator[LoadedTable]:
    """Charge un fichier tabulaire dans une connexion DuckDB temporaire.

    Lit directement depuis RustFS/S3 via l'extension ``httpfs`` de DuckDB -
    pas de ``get_object`` préalable, pas de fichier temporaire pour le source
    (sauf XLSX qui nécessite openpyxl).

    La table DuckDB est nommée d'après ``document_id`` : permet de coexister
    avec d'autres tables dans la même connexion si besoin, et rend les logs
    plus traçables.

    Usage ::

        with load_tabular("documents/col1/doc1.csv", TabularFormat.CSV, "doc-1") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} LIMIT 5").fetchall()

    La connexion et les fichiers temporaires sont nettoyés à la sortie du
    context manager, même en cas d'erreur.
    """
    # Nom de table DuckDB : on préfixe par ``t_`` car un UUID peut commencer
    # par un chiffre, ce qui n'est pas un identifiant SQL valide.
    table_name = f"t_{document_id.replace('-', '_')}"

    connection = duckdb.connect(":memory:")

    # Mode low-memory : limite la RAM consommée par DuckDB et le nombre
    # de threads. DuckDB spill sur disque au-delà de la limite, ce qui
    # protège le worker contre l'OOM sur les gros fichiers.
    connection.execute(f"PRAGMA memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"PRAGMA threads={DUCKDB_THREADS}")

    # Configuration S3 pour httpfs (lecture directe depuis RustFS).
    _configure_s3(connection)

    # XLSX : l'extension ``spatial`` de DuckDB sait lire le format Excel
    # directement depuis S3 (via GDAL), pas besoin de get_object ni openpyxl.
    if format == TabularFormat.XLSX:
        _configure_spatial(connection)

    source = _s3_url(storage_key)

    try:
        connection.execute(_load_statement(format, source, table_name))
        yield LoadedTable(connection=connection, format=format, table_name=table_name)
    finally:
        connection.close()
