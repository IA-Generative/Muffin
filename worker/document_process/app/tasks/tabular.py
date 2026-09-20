"""Branche tabulaire du pipeline document.

``process_tabular_document`` : charge un fichier CSV/XLSX/Parquet/JSON dans
DuckDB (temporaire), calcule les stats descriptives, persiste le profil via
``/internal/documents/{id}/tabular-profile``, puis enchaîne sur
``chunk_document`` avec une sérialisation texte du fichier (pour la recherche
vectorielle classique - voir issue #69, question ouverte 1).

Le résumé et les QA sont générés à partir du profil tabulaire (prompt dédié,
plus compact et pertinent qu'un dump CSV), mais utilisent le même mécanisme
d'envoi LLM (``_shared._chat``) et la même sauvegarde
(``set_document_summary``, ``create_qa_pair``) que les documents classiques.
``chunk_document`` est ensuite appelé avec ``skip_summary=True``,
``skip_qa=True`` et ``skip_chunking=True`` : le chunking texte d'un CSV
n'est pas pertinent pour la recherche vectorielle (le Parquet exporté et le
profil couvrent déjà l'accès aux données), donc on passe directement à
"indexed" puis on dispatche le tagging et l'extraction d'entités.

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
    generate_qa_pairs,
    generate_summary,
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
    /internal/documents/{id}/tabular-profile, génère le résumé et les QA à
    partir du profil (prompt tabulaire, mais même envoi LLM et même
    sauvegarde que les documents classiques), puis enchaîne sur chunk_document
    avec skip_summary=True, skip_qa=True et skip_chunking=True (le chunking
    texte d'un CSV n'est pas pertinent pour la recherche vectorielle).
    Le tagging et l'extraction d'entités restent gérés par les tâches
    classiques dispatchées par chunk_document."""
    with capture_task_logs(self.request.id):
        try:
            document, settings, fmt = validate_document(document_id, collection_id, tabular_format)
            _shared.backend_client.update_status(document_id, status="indexing", progress=0)

            with load_tabular(document["storage_key"], fmt, document_id) as table:
                export_parquet(table, collection_id, document_id)
                profile = compute_tabular_profile(table, document_id)
                persist_profile(profile, document_id)
                serialize_to_csv_page(table, document_id)

            # Summary and QA use tabular prompts (profile-based, more compact
            # than CSV) but the same LLM calls and persistence as classic docs.
            generate_summary(profile, document_id, collection_id, settings)
            generate_qa_pairs(profile, document_id, collection_id, settings)

            _shared.backend_client.update_status(document_id, status="indexing", progress=50)
            _shared._spawn(
                chunk_document,
                [
                    document_id,
                    collection_id,
                    True,
                    True,
                    True,
                ],  # skip_summary, skip_qa, skip_chunking
                "app.tasks.chunk_document",
                document_id,
                self.request.id,
            )
        except Exception as error:
            _shared.backend_client.update_status(document_id, status="error")
            _shared._fail(document_id, "process tabular document", error)
            raise
