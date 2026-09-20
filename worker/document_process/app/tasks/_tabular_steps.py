"""Étapes du pipeline tabulaire.

Découpe ``process_tabular_document`` en sous-fonctions testables :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``export_parquet`` : export DuckDB → S3 (RustFS) via httpfs ;
- ``compute_tabular_profile`` : calcul du profil descriptif ;
- ``persist_profile`` : sauvegarde du profil côté backend ;
- ``serialize_to_csv_page`` : sérialisation texte pour le chunking.

Le résumé et les QA ne sont **pas** générés ici : ils sont pris en charge par
les tâches classiques (``summarize_document`` et ``generate_qa_window``)
dispatchées par ``chunk_document``, exactement comme pour les documents
classiques. Le profil tabulaire ne contient donc que les stats descriptives.

Chaque fonction reçoit ses dépendances explicites (connection, client, etc.)
pour faciliter le test unitaire.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.tabular.loader import LoadedTable
from app.tabular.stats import TabularProfile, compute_profile
from app.tasks import _shared


def validate_document(
    document_id: str,
    collection_id: str,
    tabular_format: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Récupère et valide le document + settings + format.

    Returns: (document, settings, fmt) où fmt est le TabularFormat validé.
    Raises: ValueError si le MIME type n'est pas supporté.
    """
    from app.tabular.detect import TabularFormat, is_supported_mime

    document = _shared.backend_client.get_document(document_id)
    settings = _shared.backend_client.get_collection_settings(collection_id)
    fmt = TabularFormat(tabular_format)
    logger.info(f"Processing tabular document {document_id} (format={fmt}): {document['name']}")

    mime_type = document.get("mime_type", "")
    if mime_type and not is_supported_mime(mime_type):
        raise ValueError(f"Unsupported MIME type for tabular analysis: {mime_type} (document {document_id})")

    return document, settings, fmt


def export_parquet(table: LoadedTable, collection_id: str, document_id: str) -> str:
    """Exporte la table DuckDB vers RustFS au format Parquet via httpfs.

    Returns: la clé S3 du fichier Parquet créé.
    """
    parquet_key = f"documents/{collection_id}/{document_id}.parquet"
    table.connection.execute(
        f"COPY (SELECT * FROM {table.table_name}) TO 's3://{_shared.storage._bucket}/{parquet_key}' (FORMAT PARQUET)"
    )
    logger.info(f"Saved Parquet for document {document_id} at {parquet_key}")
    return parquet_key


def compute_tabular_profile(table: LoadedTable, document_id: str) -> TabularProfile:
    """Calcule le profil descriptif de la table et logge le résumé."""
    profile = compute_profile(table)
    logger.info(
        f"Tabular profile for {document_id}: {profile.row_count} rows, "
        f"{profile.column_count} columns, "
        f"{len(profile.measures)} measures, "
        f"{len(profile.dimensions)} dimensions, "
        f"{len(profile.text_columns)} text columns"
    )
    return profile


def persist_profile(profile: TabularProfile, document_id: str) -> None:
    """Persiste le profil tabulaire (stats + schéma + échantillon +
    classification) côté backend.

    Le résumé et les questions suggérées ne sont **pas** inclus ici : ils
    sont générés et persistés par les tâches classiques (``summarize_document``
    et ``generate_qa_window``) dispatchées par ``chunk_document``.
    """
    profile_dict = profile.to_dict()
    profile_dict["document_id"] = document_id
    _shared.backend_client.set_tabular_profile(document_id, profile_dict)


def serialize_to_csv_page(table: LoadedTable, document_id: str) -> None:
    """Sérialise la table en CSV (depuis DuckDB) et l'écrit comme une
    seule page de texte pour le chunker classique."""
    csv_text = table.connection.execute(
        f"COPY (SELECT * FROM {table.table_name}) TO '/dev/stdout' (HEADER, DELIMITER ',')"
    ).fetchall()
    page_content = "\n".join(row[0] for row in csv_text if row and row[0])
    _shared.backend_client.add_page(document_id, page_number=1, content=page_content)
