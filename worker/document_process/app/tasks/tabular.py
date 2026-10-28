"""Branche tabulaire du pipeline document.

``process_tabular_document`` : lit un fichier CSV/TSV/PSV/XLSX/XLS/ODS/JSON/JSONL/Parquet en flux (toutes ses
feuilles), en écrit une copie Parquet typée par feuille, calcule le profil du document et celui de chaque feuille,
les persiste via ``/internal/documents/{id}/tabular-profile``, puis enchaîne sur
``chunk_document`` avec une sérialisation texte du fichier, une page CSV par feuille (voir issue #69, question
ouverte 1).

Le résumé et les QA sont générés à partir du profil tabulaire (prompt dédié,
plus compact et pertinent qu'un dump CSV), mais utilisent le même mécanisme
d'envoi LLM (``_shared._chat``) et la même sauvegarde
(``set_document_summary``, ``replace_generated_qa``) que les documents classiques.
``chunk_document`` est ensuite appelé avec ``skip_summary=True``,
    ``skip_qa=True``, ``skip_chunking=True`` et ``skip_extraction=True`` :
    le chunking texte d'un CSV n'est pas pertinent pour la recherche
    vectorielle (les Parquet par feuille et le profil couvrent déjà l'accès aux
    données), et l'extraction d'entités sur des lignes CSV est lente et
    faible valeur (le profil capture déjà la structure), donc on passe
    directement à "indexed".
Les étapes du pipeline sont découpées dans ``app/tasks/_tabular_steps.py``
pour faciliter le test unitaire de chaque phase.
"""

from pathlib import Path

from app.celery_app import celery_app
from app.config import settings as worker_settings
from app.tabular.sheets import compat
from app.tabular.sheets.limits import Limits
from app.tasks import _shared
from app.tasks._tabular_steps import (
    analyze,
    build_profile,
    downloaded,
    generate_qa_pairs,
    generate_summary,
    persist_profile,
    source_name,
    validate_document,
    write_pages,
    write_tables,
)

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401


@celery_app.task(name="app.tasks.process_tabular_document", bind=True)
def process_tabular_document(self, document_id: str, collection_id: str, tabular_format: str) -> None:
    """Branche tabulaire du pipeline : lit le fichier en flux (toutes ses feuilles), en tire une copie
    Parquet typée de chaque feuille et son profil, persiste le profil via
    /internal/documents/{id}/tabular-profile, génère le résumé et les QA à
    partir du profil (prompt tabulaire, mais même envoi LLM et même
    sauvegarde que les documents classiques), puis enchaîne sur chunk_document
    avec skip_summary=True, skip_qa=True et skip_chunking=True (le chunking
    texte d'un CSV n'est pas pertinent pour la recherche vectorielle).
    Le tagging et l'extraction d'entités restent gérés par les tâches
    classiques dispatchées par chunk_document."""
    try:
        document, settings, fmt = validate_document(document_id, collection_id, tabular_format)
        _shared.backend_client.update_status(document_id, status="indexing", progress=0)

        limits = Limits()
        file_name = source_name(document, fmt)
        with downloaded(document["storage_key"], limits, Path(file_name).suffix) as path:
            analysis = analyze(path, file_name, limits, document_id)
            described, keys, folder = write_tables(path, file_name, analysis, collection_id, document_id, limits)
            profile = build_profile(analysis, fmt, document_id)
            persist_profile(profile, document_id, compat.sheets_payload(analysis, described, keys))
            write_pages(folder, analysis, described, document_id, worker_settings.TABULAR_PAGE_MAX_ROWS)

        # Summary and QA use tabular prompts (profile-based, more compact
        # than CSV) but the same LLM calls and persistence as classic docs.
        generate_summary(profile, document_id, collection_id, settings)
        generate_qa_pairs(profile, document_id, collection_id, settings)

        _shared.backend_client.update_status(document_id, status="indexing", progress=50)
        # The extraction is over: a document of a ZIP import frees its place in its window (#335).
        _shared._extraction_done(document_id)
        _shared._spawn(
            chunk_document,
            [
                document_id,
                collection_id,
                True,
                True,
                True,
                True,
            ],  # skip_summary, skip_qa, skip_chunking, skip_extraction
            "app.tasks.chunk_document",
            document_id,
            self.request.id,
        )
    except Exception as error:
        _shared.backend_client.update_status(document_id, status="error")
        _shared._fail(document_id, "process tabular document", error)
        raise
