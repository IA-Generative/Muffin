"""Tâches d'entrée du pipeline : extraction de contenu et branchement
tabulaire.

- ``process_document`` : point d'entrée, extrait le contenu brut (scraping
  pour URLs, liteparse pour fichiers uploadés) et écrit les pages. Pas de
  chunking ici — c'est ``chunk_document`` qui s'en charge.
- ``process_tabular_document`` : branche tabulaire, charge le fichier dans
  DuckDB (temporaire), calcule les stats, génère résumé + QA, puis enchaîne
  sur ``chunk_document``.
"""

from loguru import logger

from app.celery_app import celery_app
from app.tabular.detect import detect_tabular
from app.tabular.loader import load_tabular
from app.tabular.qa import generate_qa as generate_tabular_qa
from app.tabular.stats import compute_profile
from app.tabular.summarize import build_summary_prompt
from app.task_logging import capture_task_logs
from app.tasks import _shared

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401


def _process_url(document_id: str, url: str) -> None:
    markdown = _shared.fetch_url_markdown(url)
    _shared.backend_client.add_page(document_id, page_number=1, content=markdown)


def _process_file(document_id: str, storage_key: str, data: bytes | None = None) -> None:
    if data is None:
        data = _shared.storage.get_object(storage_key)
    result = _shared.parse_file(data)
    screenshots_by_page = {screenshot.page_num: screenshot for screenshot in result.screenshots}

    for page in result.pages:
        screenshot_key: str | None = None
        screenshot = screenshots_by_page.get(page.page_num)
        if screenshot is not None:
            screenshot_key = f"screenshots/{document_id}/page-{page.page_num}.png"
            _shared.storage.put_object(screenshot_key, screenshot.image_bytes, content_type="image/png")
        _shared.backend_client.add_page(
            document_id,
            page_number=page.page_num,
            content=page.text,
            screenshot=screenshot_key,
        )


@celery_app.task(name="app.tasks.process_document", bind=True)
def process_document(self, document_id: str) -> None:
    """Entry point: extract raw content (scraping for URLs, liteparse for
    uploaded files) and write pages back to the backend. No chunking here -
    that's chunk_document's job, so it can apply the collection's configured
    strategy instead of liteparse's raw layout blocks."""
    with capture_task_logs(self.request.id):
        try:
            document = _shared.backend_client.get_document(document_id)
            logger.info(f"Processing document {document_id} ({document['type']}): {document['name']}")
            _shared.backend_client.update_status(document_id, status="indexing", progress=0)

            if document["type"] == "url":
                _process_url(document_id, document["name"])
                _shared.backend_client.update_status(document_id, status="indexing", progress=50)
                _shared._spawn(
                    chunk_document,
                    [document_id, document["collection_id"]],
                    "app.tasks.chunk_document",
                    document_id,
                    self.request.id,
                )
            else:
                if not document["storage_key"]:
                    raise ValueError(f"Document {document_id} has no storage_key to fetch from RustFS")
                data = _shared.storage.get_object(document["storage_key"])
                tabular_format = detect_tabular(document["name"], data)
                if tabular_format is not None:
                    _shared._spawn(
                        process_tabular_document,
                        [document_id, document["collection_id"], tabular_format.value],
                        "app.tasks.process_tabular_document",
                        document_id,
                        self.request.id,
                    )
                else:
                    _process_file(document_id, document["storage_key"], data)
                    _shared.backend_client.update_status(document_id, status="indexing", progress=50)
                    _shared._spawn(
                        chunk_document,
                        [document_id, document["collection_id"]],
                        "app.tasks.chunk_document",
                        document_id,
                        self.request.id,
                    )
        except Exception as error:
            _shared.backend_client.update_status(document_id, status="error")
            _shared._fail(document_id, "extract content", error)
            raise


@celery_app.task(name="app.tasks.process_tabular_document", bind=True)
def process_tabular_document(self, document_id: str, collection_id: str, tabular_format: str) -> None:
    """Branche tabulaire du pipeline : charge le fichier dans DuckDB
    (temporaire), calcule les stats descriptives, persiste le profil via
    /internal/documents/{id}/tabular-profile, génère un résumé et des QA
    ancrées dans les données réelles, puis enchaîne sur chunk_document avec
    une sérialisation texte du fichier (pour la recherche vectorielle
    classique - voir issue #69, question ouverte 1)."""
    from app.tabular.detect import TabularFormat, is_supported_mime

    with capture_task_logs(self.request.id):
        try:
            document = _shared.backend_client.get_document(document_id)
            settings = _shared.backend_client.get_collection_settings(collection_id)
            fmt = TabularFormat(tabular_format)
            logger.info(f"Processing tabular document {document_id} (format={fmt}): {document['name']}")

            # Validation MIME type : on vérifie que le type déclaré par le
            # backend est supporté avant de tenter un chargement. Si le
            # backend ne fournit pas de mime_type, on fait confiance au
            # format détecté par l'extension.
            mime_type = document.get("mime_type", "")
            if mime_type and not is_supported_mime(mime_type):
                raise ValueError(f"Unsupported MIME type for tabular analysis: {mime_type} (document {document_id})")

            _shared.backend_client.update_status(document_id, status="indexing", progress=0)
            data = _shared.storage.get_object(document["storage_key"])

            with load_tabular(data, fmt) as table:
                profile = compute_profile(table)
                logger.info(
                    f"Tabular profile for {document_id}: {profile.row_count} rows, "
                    f"{profile.column_count} columns, "
                    f"{len(profile.measures)} measures, "
                    f"{len(profile.dimensions)} dimensions, "
                    f"{len(profile.text_columns)} text columns"
                )

                # Résumé tabulaire : un seul appel LLM (pas de map-reduce,
                # le profil est compact par construction).
                summary_model = _shared._model_for(settings, "summary")
                summary_text = ""
                if summary_model is not None:
                    instructions = settings["instructions"].get("summary", "")
                    system, user_content = build_summary_prompt(profile, instructions)
                    summary_text = _shared._chat(summary_model, system, user_content)

                    summary_embedding = None
                    try:
                        summary_embedding = _shared.backend_client.embed(settings["embedding_model"], summary_text)
                    except Exception:
                        logger.exception(f"Failed to embed tabular summary for document {document_id}")
                    _shared.backend_client.set_document_summary(document_id, summary_text, summary_embedding)
                    logger.info(f"Tabular summary for document {document_id} saved ({len(summary_text)} chars)")
                else:
                    logger.warning(f"No summary model for collection {collection_id}, skipping tabular summary")

                # QA ancrées dans les données réelles.
                qa_model = _shared._model_for(settings, "qa")
                suggested_questions: list[dict[str, str]] = []
                if qa_model is not None:
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
                else:
                    logger.warning(f"No QA model for collection {collection_id}, skipping tabular QA")

                # Persiste le profil enrichi (stats + schéma + échantillon +
                # classification + résumé + questions suggérées).
                profile_dict = profile.to_dict()
                profile_dict["document_id"] = document_id
                profile_dict["summary"] = summary_text
                profile_dict["suggested_questions"] = [q["question"] for q in suggested_questions]
                _shared.backend_client.set_tabular_profile(document_id, profile_dict)

                # Sérialisation texte pour le chunking : on réexporte la table
                # en CSV depuis DuckDB, puis on l'écrit comme une seule page
                # de texte (le chunker classique s'en occupe ensuite).
                csv_text = table.connection.execute(
                    f"COPY (SELECT * FROM {table.table_name}) TO '/dev/stdout' (HEADER, DELIMITER ',')"
                ).fetchall()
                # COPY TO '/dev/stdout' renvoie aussi les lignes - on les rejoint.
                page_content = "\n".join(row[0] for row in csv_text if row and row[0])
                _shared.backend_client.add_page(document_id, page_number=1, content=page_content)

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
