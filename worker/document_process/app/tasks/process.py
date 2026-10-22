"""Tâche d'entrée du pipeline : extraction de contenu.

``process_document`` : point d'entrée, extrait le contenu brut (scraping
pour URLs, liteparse pour fichiers uploadés) et écrit les pages. Pas de
chunking ici — c'est ``chunk_document`` qui s'en charge. La branche
tabulaire est dans ``app/tasks/tabular.py``.
"""

import hashlib

from loguru import logger

from app import reuse
from app.celery_app import celery_app
from app.tabular.detect import detect_tabular
from app.tasks import _shared

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401
from app.tasks.tabular import process_tabular_document  # noqa: E402,F401


def _process_url(document: dict) -> dict | None:
    """An HTML page is written as one page. A URL serving a file (PDF, Office, image, text, tabular)
    has it downloaded and stored like an upload: returns the document as the usual file branch reads
    it - its storage_key, and a name whose extension says its format."""
    document_id = document["id"]
    fetched = _shared.fetch_url(document["name"])
    if fetched.data is None:
        # The page's text is its "file" (#300): the same text in another document is the same pages.
        content_hash = fetched.content_hash
        extraction = reuse.extraction(content_hash)
        if not reuse.begin(document_id, reuse.EXTRACTION, extraction, content_hash=content_hash):
            _shared.backend_client.add_page(document_id, page_number=1, content=fetched.markdown)
            _shared.backend_client.prune_pages(document_id, keep=1)
            reuse.done(document_id, reuse.EXTRACTION)
        # What a scheduled refresh (#19) compares the page against next time.
        _shared.backend_client.set_content_hash(document_id, content_hash)
        return None
    # One key per document, overwritten when a refresh fetches a new version of the file.
    storage_key = f"documents/{document['collection_id']}/{document_id}-{fetched.filename}"
    _shared.storage.put_object(storage_key, fetched.data, content_type=fetched.content_type)
    _shared.backend_client.set_content_hash(document_id, fetched.content_hash, storage_key=storage_key)
    return {
        **document,
        "name": fetched.filename,
        "storage_key": storage_key,
        "content_hash": fetched.content_hash,
    }


# Already text - one page, no liteparse, no screenshot. liteparse only handles PDF/Office/image
# formats; plain text files arrive notably through a ZIP import (#223).
_TEXT_EXTENSIONS = (".md", ".txt")


def _process_markdown(document_id: str, data: bytes) -> None:
    """A Markdown (living documents, #166) or plain text file."""
    _shared.backend_client.add_page(document_id, page_number=1, content=data.decode("utf-8", errors="replace"))
    _shared.backend_client.prune_pages(document_id, keep=1)


def _extract_file(document: dict) -> None:
    """The pages of a file - unless another document of the same file already has them (#300), in which
    case the backend copies them and the OCR is not run."""
    document_id, storage_key = document["id"], document["storage_key"]
    content_hash = reuse.valid_hash(document.get("content_hash"))
    data = None
    if content_hash is None:
        # A file added before its hash was kept, or whose file was replaced: hashed here, from the bytes
        # that are about to be parsed anyway.
        data = _shared.storage.get_object(storage_key)
        content_hash = hashlib.sha256(data).hexdigest()
    if reuse.begin(document_id, reuse.EXTRACTION, reuse.extraction(content_hash), content_hash=content_hash):
        return
    if data is None:
        data = _shared.storage.get_object(storage_key)
    _process_file(document_id, storage_key, data, document["name"])
    reuse.done(document_id, reuse.EXTRACTION)


def _process_file(document_id: str, storage_key: str, data: bytes | None = None, name: str = "") -> None:
    if data is None:
        data = _shared.storage.get_object(storage_key)
    if name.lower().endswith(_TEXT_EXTENSIONS):
        _process_markdown(document_id, data)
        return
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
    # Pages are written with an upsert, so a task run twice leaves the same pages; what a previous
    # run found after the last one (#299) is dropped.
    _shared.backend_client.prune_pages(document_id, keep=max((page.page_num for page in result.pages), default=0))


def _spawn_chunking(document: dict, parent_task_id: str) -> None:
    _shared._spawn(
        chunk_document,
        [document["id"], document["collection_id"]],
        "app.tasks.chunk_document",
        document["id"],
        parent_task_id,
    )


@celery_app.task(name="app.tasks.process_document", bind=True)
def process_document(self, document_id: str) -> None:
    """Entry point: extract raw content (scraping for URLs, liteparse for
    uploaded files) and write pages back to the backend. No chunking here -
    that's chunk_document's job, so it can apply the collection's configured
    strategy instead of liteparse's raw layout blocks."""
    try:
        document = _shared.backend_client.get_document(document_id)
        logger.info(f"Processing document {document_id} ({document['type']}): {document['name']}")
        _shared.backend_client.update_status(document_id, status="indexing", progress=0)

        if document["type"] == "url":
            stored = _process_url(document)
            if stored is None:
                _shared.backend_client.update_status(document_id, status="indexing", progress=50)
                _spawn_chunking(document, self.request.id)
                return
            document = stored
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
            _extract_file(document)
            _shared.backend_client.update_status(document_id, status="indexing", progress=50)
            _spawn_chunking(document, self.request.id)
    except Exception as error:
        _shared.backend_client.update_status(document_id, status="error")
        _shared._fail(document_id, "extract content", error)
        raise
