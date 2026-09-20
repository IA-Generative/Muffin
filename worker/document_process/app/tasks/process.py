"""Tâche d'entrée du pipeline : extraction de contenu.

``process_document`` : point d'entrée, extrait le contenu brut (scraping
pour URLs, liteparse pour fichiers uploadés) et écrit les pages. Pas de
chunking ici — c'est ``chunk_document`` qui s'en charge. La branche
tabulaire est dans ``app/tasks/tabular.py``.
"""

from loguru import logger

from app.celery_app import celery_app
from app.tabular.detect import detect_tabular
from app.task_logging import capture_task_logs
from app.tasks import _shared

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401
from app.tasks.tabular import process_tabular_document  # noqa: E402,F401


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
                # Détection tabulaire par extension + HEAD S3 (Content-Type)
                # avant tout GET : si le fichier est tabulaire, on spawn
                # process_tabular_document sans télécharger le contenu ici -
                # c'est cette tâche qui fera son propre GET pour le chargement
                # DuckDB. Le sniff du contenu (detect_by_content) n'est pas
                # déclenché ici (pas de data), c'est un fallback coûteux.
                tabular_format = detect_tabular(document["name"], storage_key=document["storage_key"])
                if tabular_format is not None:
                    _shared._spawn(
                        process_tabular_document,
                        [document_id, document["collection_id"], tabular_format.value],
                        "app.tasks.process_tabular_document",
                        document_id,
                        self.request.id,
                    )
                else:
                    data = _shared.storage.get_object(document["storage_key"])
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
