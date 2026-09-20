"""Étapes du pipeline tabulaire.

Découpe ``process_tabular_document`` en sous-fonctions testables :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``export_parquet`` : export DuckDB → S3 (RustFS) via httpfs ;
- ``compute_tabular_profile`` : calcul du profil descriptif ;
- ``persist_profile`` : sauvegarde du profil côté backend ;
- ``serialize_to_csv_page`` : sérialisation texte pour le chunking ;
- ``generate_summary`` : résumé LLM basé sur le profil (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques) ;
- ``generate_qa_pairs`` : paires QA ancrées dans les stats (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques).

Le résumé et les QA utilisent les prompts tabulaires (``app.tabular.summarize``)
car le profil est plus compact et pertinent qu'un dump CSV, mais ils sont
envoyés via ``_shared._chat`` et sauvés via ``set_document_summary`` /
``create_qa_pair`` — exactement comme ``summarize_document`` et
``generate_qa_window`` le font pour les documents classiques.

Chaque fonction reçoit ses dépendances explicites (connection, client, etc.)
pour faciliter le test unitaire.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from loguru import logger

from app.tabular.loader import LoadedTable
from app.tabular.stats import TabularProfile, compute_profile
from app.tabular.summarize import (
    build_qa_prompt,
    build_summary_prompt,
    parse_qa_response,
)
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
    rows = table.connection.execute(f"SELECT * FROM {table.table_name}").fetchall()
    columns = [desc[0] for desc in table.connection.description]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    page_content = buffer.getvalue()
    _shared.backend_client.add_page(document_id, page_number=1, content=page_content)


def generate_summary(
    profile: TabularProfile,
    document_id: str,
    collection_id: str,
    settings: dict[str, Any],
) -> str:
    """Génère le résumé LLM du fichier tabulaire à partir de son profil.

    Utilise le prompt tabulaire (``build_summary_prompt``) car le profil est
    plus compact et pertinent qu'un dump CSV, mais utilise le même mécanisme
    d'envoi LLM (``_shared._chat``) et la même sauvegarde
    (``set_document_summary`` avec embedding) que ``summarize_document`` pour
    les documents classiques.

    Returns: le texte du résumé généré.
    """
    model = _shared._model_for(settings, "summary")
    if model is None:
        logger.warning(f"No summary model configured for collection {collection_id}, skipping tabular summary")
        return ""

    instructions = settings["instructions"].get("summary", "")
    system, user_content = build_summary_prompt(profile, instructions)
    logger.info(f"Generating tabular summary for document {document_id} (model={model})")
    summary = _shared._chat(model, system, user_content)

    # Best-effort embedding, same fail-soft as summarize_document.
    summary_embedding = None
    try:
        summary_embedding = _shared.backend_client.embed(settings["embedding_model"], summary)
    except Exception:
        logger.exception(f"Failed to embed tabular summary for document {document_id}")

    _shared.backend_client.set_document_summary(document_id, summary, summary_embedding)
    logger.info(f"Tabular summary for document {document_id} saved ({len(summary)} chars)")
    return summary


def generate_qa_pairs(
    profile: TabularProfile,
    document_id: str,
    collection_id: str,
    settings: dict[str, Any],
) -> list[dict[str, str]]:
    """Génère des paires QA ancrées dans les stats tabulaires.

    Utilise le prompt tabulaire (``build_qa_prompt``) car les questions
    portent sur des comptages/agrégations déduits des stats, mais utilise le
    même mécanisme d'envoi LLM (``_shared._chat``) et la même sauvegarde
    (``create_qa_pair`` avec embedding) que ``generate_qa_window`` pour les
    documents classiques.

    Returns: la liste des paires {"question": ..., "answer": ...} générées.
    """
    model = _shared._model_for(settings, "qa")
    if model is None:
        logger.warning(f"No QA model configured for collection {collection_id}, skipping tabular QA")
        return []

    instructions = settings["instructions"].get("qa", "")
    k = _shared._windows(settings)["qa_questions_per_window"]
    system, user_content = build_qa_prompt(profile, instructions, k)
    logger.info(f"Generating {k} tabular QA pairs for document {document_id} (model={model})")
    raw = _shared._chat(model, system, user_content)
    pairs = parse_qa_response(raw)
    logger.info(f"Generated {len(pairs)} tabular QA pairs for document {document_id}")

    for pair in pairs:
        question, answer = pair["question"], pair["answer"]
        # Best-effort embedding, same fail-soft as generate_qa_window.
        embedding = None
        try:
            embedding = _shared.backend_client.embed(settings["embedding_model"], question)
        except Exception:
            logger.exception(f"Failed to embed tabular QA question for document {document_id}")
        _shared.backend_client.create_qa_pair(collection_id, document_id, question, answer, embedding)

    return pairs
