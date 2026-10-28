"""Étapes du pipeline tabulaire.

Découpe ``process_tabular_document`` en sous-fonctions testables :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``downloaded`` : le fichier, téléchargé dans un dossier temporaire (taille vérifiée avant) ;
- ``analyze`` : l'analyse du fichier en flux (``app.tabular.sheets``), toutes ses feuilles ;
- ``write_tables`` : une copie Parquet typée de chaque feuille, déposée dans S3 (RustFS) ;
- ``build_profile`` : le profil du document (sa feuille principale) tiré de l'analyse ;
- ``persist_profile`` : sauvegarde du profil et des feuilles côté backend ;
- ``write_pages`` : le texte du fichier, une page CSV par feuille ;
- ``generate_summary`` : résumé LLM basé sur le profil (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques) ;
- ``generate_qa_pairs`` : paires QA ancrées dans les stats (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques).

Le fichier n'est plus chargé dans DuckDB depuis S3 : il est lu en flux, une ligne à la fois, par des lecteurs qui
savent les formats tableur (csv, xlsx, xls, ods) et, pour les autres (json, jsonl, parquet), par DuckDB sur le fichier
local. Ni ``httpfs`` ni ``spatial``, donc ni identifiants S3 ni accès réseau dans le moteur de lecture.

Le résumé et les QA utilisent les prompts tabulaires (``app.tabular.summarize``)
car le profil est plus compact et pertinent qu'un dump CSV, mais ils sont
envoyés via ``_shared._chat`` et sauvés via ``set_document_summary`` /
``replace_generated_qa`` — exactement comme ``summarize_document`` et
``generate_qa_window`` le font pour les documents classiques.

Chaque fonction reçoit ses dépendances explicites pour faciliter le test unitaire.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger

from app.tabular.sheets import analyzer, compat, pages, tables
from app.tabular.sheets.limits import Limits
from app.tabular.stats import TabularProfile
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


def source_name(document: dict[str, Any], fmt: Any) -> str:
    """The name the readers detect the format by: the document's own, with the extension of the format it was
    recognized as - a file recognized by its content has none, or a wrong one."""
    return f"{Path(document['name']).stem or 'data'}.{fmt.value}"


@contextmanager
def downloaded(storage_key: str, limits: Limits, suffix: str = "") -> Iterator[Path]:
    """The file, downloaded into a temporary folder that goes with the block. Refused before downloading if it is
    over `limits.max_file_bytes`. `suffix` (".xlsx"): the libraries that read a workbook go by the file's extension."""
    size = _shared.storage.head_object(storage_key)["ContentLength"]
    if size > limits.max_file_bytes:
        raise ValueError(f"File too large: {size // 2**20} MB, the limit is {limits.max_file_bytes // 2**20} MB")
    with tempfile.TemporaryDirectory(prefix="tabular-") as folder:
        path = Path(folder) / f"source{suffix}"
        with path.open("wb") as handle:
            _shared.storage.download_fileobj(storage_key, handle)
        yield path


def analyze(path: Path, file_name: str, limits: Limits, document_id: str) -> dict[str, Any]:
    """The analysis of the file: every sheet, its columns and their types. Raises ValueError for a file with no data
    - an empty document would be indexed and answer nothing."""
    analysis = analyzer.analyze_file(path, file_name, limits)
    sheets = [sheet for sheet in analysis["sheets"] if sheet["rows"] and sheet["columns"]]
    if not sheets:
        raise ValueError("The file contains no data")
    logger.info(
        f"Tabular analysis of {document_id}: {len(analysis['sheets'])} sheet(s), {analysis['summary']['rows']} rows"
        + (", truncated" if analysis["summary"]["truncated"] else "")
    )
    return analysis


def table_prefix(collection_id: str, document_id: str) -> str:
    return f"documents/{collection_id}/{document_id}/tables/"


def write_tables(
    path: Path, file_name: str, analysis: dict[str, Any], collection_id: str, document_id: str, limits: Limits
) -> tuple[dict[int, dict], dict[int, str], Path]:
    """The typed copy of each sheet that has rows, in S3 (`documents/<collection>/<document>/tables/<n>.parquet`), in
    place of what a former extraction left there - and the old single-file copy of before the sheets.

    Returns (the description of each table, its S3 key, the local folder holding the copies - for the text pages;
    it lives as long as the caller's temporary folder)."""
    folder = path.parent / "tables"
    folder.mkdir(exist_ok=True)
    described = tables.write_tables(path, file_name, analysis, folder, limits)
    prefix = table_prefix(collection_id, document_id)
    _shared.storage.delete_prefix(prefix)
    _shared.storage.delete_objects([f"documents/{collection_id}/{document_id}.parquet"])
    keys: dict[int, str] = {}
    for index in sorted(described):
        keys[index] = f"{prefix}{index}.parquet"
        with (folder / f"{index}.parquet").open("rb") as handle:
            _shared.storage.upload_fileobj(keys[index], handle, content_type="application/vnd.apache.parquet")
    logger.info(f"Saved {len(keys)} typed table(s) for document {document_id} under {prefix}")
    return described, keys, folder


def build_profile(analysis: dict[str, Any], fmt: Any, document_id: str) -> TabularProfile:
    """Le profil du document (sa feuille principale) et son log."""
    profile = compat.profile_from_analysis(analysis, fmt.value)
    logger.info(
        f"Tabular profile for {document_id}: {profile.row_count} rows, "
        f"{profile.column_count} columns, "
        f"{len(profile.measures)} measures, "
        f"{len(profile.dimensions)} dimensions, "
        f"{len(profile.text_columns)} text columns"
        + (f", main sheet '{profile.primary_sheet}' of {len(profile.sheets)}" if len(profile.sheets) > 1 else "")
    )
    return profile


def persist_profile(
    profile: TabularProfile,
    document_id: str,
    sheets: list[dict[str, Any]] | None = None,
) -> None:
    """Persiste le profil tabulaire (stats + schéma + échantillon +
    classification) et les feuilles du fichier côté backend.

    Le résumé et les questions suggérées ne sont **pas** inclus ici : ils
    sont générés et persistés par les tâches classiques (``summarize_document``
    et ``generate_qa_window``) dispatchées par ``chunk_document``.
    """
    profile_dict = profile.to_dict()
    profile_dict["document_id"] = document_id
    if sheets is not None:
        profile_dict["sheets"] = sheets
        profile_dict["analysis_version"] = compat.ANALYSIS_VERSION
    _shared.backend_client.set_tabular_profile(document_id, profile_dict)


def write_pages(
    folder: Path, analysis: dict[str, Any], described: dict[int, dict], document_id: str, max_rows: int
) -> int:
    """The text of the file, one CSV page per sheet that has a table, in place of what a former extraction wrote.
    Returns how many pages there are."""
    contents = pages.csv_pages(folder, analysis, described, max_rows)
    for number, content in enumerate(contents, start=1):
        _shared.backend_client.add_page(document_id, page_number=number, content=content)
    _shared.backend_client.prune_pages(document_id, keep=len(contents))
    return len(contents)


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
    (``replace_generated_qa`` avec embedding) que ``generate_qa_window`` pour les
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

    generated = []
    for pair in pairs:
        question, answer = pair["question"], pair["answer"]
        # Best-effort embedding, same fail-soft as generate_qa_window.
        embedding = None
        try:
            embedding = _shared.backend_client.embed(settings["embedding_model"], question)
        except Exception:
            logger.exception(f"Failed to embed tabular QA question for document {document_id}")
        generated.append({"question": question, "answer": answer, "embedding": embedding})
    # In place of what an earlier run recorded for this document (#299), like the windows of a classic one.
    _shared.backend_client.replace_generated_qa(collection_id, document_id, "tabular", generated)

    return pairs
