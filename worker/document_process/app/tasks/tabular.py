"""Branche tabulaire du pipeline document.

``process_tabular_document`` : charge un fichier CSV/XLSX/Parquet/JSON dans
DuckDB (temporaire), calcule les stats descriptives, persiste le profil via
``/internal/documents/{id}/tabular-profile``, puis enchaîne sur
``chunk_document`` avec une sérialisation texte du fichier (pour la recherche
vectorielle classique - voir issue #69, question ouverte 1).

Le résumé et les QA sont générés par les tâches classiques
(``summarize_document`` et ``generate_qa_window``) dispatchées par
``chunk_document``, exactement comme pour les documents classiques.

Les étapes du pipeline sont découpées dans ``app/tasks/_tabular_steps.py``
pour faciliter le test unitaire de chaque phase.
"""

from app.celery_app import celery_app
from app.tabular.loader import load_tabular
from app.task_logging import capture_task_logs
from app.tasks import _shared
from app.tasks._tabular_steps import (
    compute_tabular_profile,
    export_parquet,
    persist_profile,
    serialize_to_csv_page,
    validate_document,
)

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401


@celery_app.task(name="app.tasks.process_tabular_document", bind=True)
def process_tabular_document(self, document_id: str, collection_id: str, tabular_format: str) -> None:
    """Branche tabulaire du pipeline : charge le fichier dans DuckDB
    (temporaire), calcule les stats descriptives, persiste le profil via
    /internal/documents/{id}/tabular-profile, puis enchaîne sur chunk_document
    avec une sérialisation texte du fichier. Le résumé, le tagging et les QA
    sont ensuite gérés par les tâches classiques dispatchées par
    chunk_document (summarize_document, generate_qa_window, etc.)."""
    with capture_task_logs(self.request.id):
        try:
            document, settings, fmt = validate_document(document_id, collection_id, tabular_format)
            _shared.backend_client.update_status(document_id, status="indexing", progress=0)

            with load_tabular(document["storage_key"], fmt, document_id) as table:
                export_parquet(table, collection_id, document_id)
                profile = compute_tabular_profile(table, document_id)
                persist_profile(profile, document_id)
                serialize_to_csv_page(table, document_id)

            _shared.backend_client.update_status(document_id, status="indexing", progress=50)
            _shared._spawn(
                chunk_document,
                [document_id, collection_id],
                "app.tasks.chunk_document",
                document_id,
                self.request.id,
            )
        except Exception as error:
            _shared.backend_client.update_status(document_id, status="error")
            _shared._fail(document_id, "process tabular document", error)
            raise
