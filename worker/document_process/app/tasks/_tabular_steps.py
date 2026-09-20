"""Étapes du pipeline tabulaire.

Découpe ``process_tabular_document`` en sous-fonctions testables :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``export_parquet`` : export DuckDB → S3 (RustFS) via httpfs ;
- ``generate_summary`` : résumé LLM ancré dans le profil ;
- ``generate_qa_pairs`` : QA ancrées dans les données réelles ;
- ``persist_profile`` : sauvegarde du profil enrichi côté backend ;
- ``serialize_to_csv_page`` : sérialisation texte pour le chunking.

Chaque fonction reçoit ses dépendances explicites (connection, client, etc.)
pour faciliter le test unitaire.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.tabular.loader import LoadedTable
from app.tabular.qa import generate_qa as generate_tabular_qa
from app.tabular.stats import TabularProfile, compute_profile
from app.tabular.summarize import build_summary_prompt
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


def generate_summary(
    profile: TabularProfile,
    settings: dict[str, Any],
    document_id: str,
    collection_id: str,
) -> str:
    """Génère le résumé LLM ancré dans le profil et le persiste.

    Returns: le texte du résumé (vide si pas de modèle configuré).
    """
    summary_model = _shared._model_for(settings, "summary")
    if summary_model is None:
        logger.warning(f"No summary model for collection {collection_id}, skipping tabular summary")
        return ""

    instructions = settings["instructions"].get("summary", "")
    system, user_content = build_summary_prompt(profile, instructions)
    summary_text = _shared._chat(summary_model, system, user_content)

    summary_embedding = None
    try:
        summary_embedding = _shared.backend_client.embed(settings["embedding_model"], summary_text)
    except Exception:
        logger.exception(f"Failed to embed tabular summary for document {document_id}")
    _shared.backend_client.set_document_summary(document_id, summary_text, summary_embedding)
    logger.info(f"Tabular summary for {document_id} saved ({len(summary_text)} chars)")
    return summary_text


def generate_qa_pairs(
    profile: TabularProfile,
    settings: dict[str, Any],
    document_id: str,
    collection_id: str,
) -> list[dict[str, str]]:
    """Génère les QA ancrées dans les données réelles et les persiste.

    Returns: liste de dicts {"question", "answer"} (vide si pas de modèle).
    """
    qa_model = _shared._model_for(settings, "qa")
    if qa_model is None:
        logger.warning(f"No QA model for collection {collection_id}, skipping tabular QA")
        return []

    instructions = settings["instructions"].get("qa", "")
    qa_count = _shared._windows(settings)["qa_questions_per_window"]
    suggested_questions = generate_tabular_qa(profile, qa_model, instructions, qa_count, _shared._chat)
    for pair in suggested_questions:
        embedding = None
        try:
            embedding = _shared.backend_client.embed(settings["embedding_model"], pair["question"])
        except Exception:
            logger.exception(f"Failed to embed tabular QA question for document {document_id}")
        _shared.backend_client.create_qa_pair(
            collection_id,
            document_id,
            pair["question"],
            pair["answer"],
            embedding,
        )
    return suggested_questions


def persist_profile(
    profile: TabularProfile,
    document_id: str,
    summary_text: str,
    suggested_questions: list[dict[str, str]],
) -> None:
    """Persiste le profil enrichi (stats + schéma + échantillon +
    classification + résumé + questions suggérées) côté backend."""
    profile_dict = profile.to_dict()
    profile_dict["document_id"] = document_id
    profile_dict["summary"] = summary_text
    profile_dict["suggested_questions"] = [q["question"] for q in suggested_questions]
    _shared.backend_client.set_tabular_profile(document_id, profile_dict)


def serialize_to_csv_page(table: LoadedTable, document_id: str) -> None:
    """Sérialise la table en CSV (depuis DuckDB) et l'écrit comme une
    seule page de texte pour le chunker classique."""
    csv_text = table.connection.execute(
        f"COPY (SELECT * FROM {table.table_name}) TO '/dev/stdout' (HEADER, DELIMITER ',')"
    ).fetchall()
    page_content = "\n".join(row[0] for row in csv_text if row and row[0])
    _shared.backend_client.add_page(document_id, page_number=1, content=page_content)
