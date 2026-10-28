"""Tâche d'entrée du pipeline : extraction de contenu.

``process_document`` : point d'entrée, extrait le contenu brut (scraping
pour URLs, liteparse pour fichiers uploadés) et écrit les pages. Pas de
chunking ici — c'est ``chunk_document`` qui s'en charge. La branche
tabulaire est dans ``app/tasks/tabular.py``.

Un long PDF n'est pas extrait d'un bloc : ``process_document`` annonce ses plages de pages comme les
morceaux du stage « extraction » et en lance ``PARSE_WINDOW``, chacune parsée par ``parse_page_range``.
Une plage qui se termine lance la suivante (une fenêtre glissante : la file ne contient jamais plus de
``PARSE_WINDOW`` plages du document) ; celle qui complète le stage lance le chunking.
"""

import contextvars
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from app import reuse
from app.celery_app import celery_app
from app.config import settings
from app.tabular.detect import detect_tabular
from app.task_revocation import TaskRevoked, raise_if_revoked
from app.tasks import _shared

# Importé ici pour que ``_spawn(chunk_document, ...)`` resolve l'objet tâche
# au moment de l'appel (Celery enregistre les tâches par nom).
from app.tasks.chunk import chunk_document  # noqa: E402,F401
from app.tasks.tabular import process_tabular_document  # noqa: E402,F401
from app.text_boxes import build_text_boxes


def _process_url(document: dict) -> dict | None:
    """An HTML page is written as one page. A URL serving a file (PDF, Office, image, text, tabular)
    has it downloaded and stored like an upload: returns the document as the usual file branch reads
    it - its storage_key, and a name whose extension says its format."""
    document_id = document["id"]
    started = time.monotonic()
    fetched = _shared.fetch_url(document["name"])
    seconds = time.monotonic() - started
    if fetched.data is None:
        logger.info(f"Fetched an HTML page in {seconds:.0f} s: {len(fetched.markdown)} characters of text")
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
    logger.info(
        f"Fetched a file in {seconds:.0f} s: {fetched.content_type}, {_megabytes(fetched.data)}, "
        f"processed as {fetched.filename}"
    )
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
_PDF_MARKER = b"%PDF-"


def _process_markdown(document_id: str, data: bytes) -> None:
    """A Markdown (living documents, #166) or plain text file."""
    _shared.backend_client.add_page(document_id, page_number=1, content=data.decode("utf-8", errors="replace"))
    _shared.backend_client.prune_pages(document_id, keep=1)


def _extract_file(document: dict, parent_task_id: str) -> bool:
    """The pages of a file - unless another document of the same file already has them (#300), in which
    case the backend copies them and the OCR is not run. True: the pages are there. False: it is a long PDF,
    whose ranges of pages are extracted by tasks of their own, the last of which goes on to the chunking."""
    document_id, storage_key = document["id"], document["storage_key"]
    content_hash = reuse.valid_hash(document.get("content_hash"))
    data = None
    if content_hash is None:
        # A file added before its hash was kept, or whose file was replaced: hashed here, from the bytes
        # that are about to be parsed anyway.
        data = _shared.storage.get_object(storage_key)
        content_hash = hashlib.sha256(data).hexdigest()
    fingerprint = reuse.extraction(content_hash)
    if reuse.begin(document_id, reuse.EXTRACTION, fingerprint, content_hash=content_hash):
        logger.info(f"Pages of document {document_id} reused from another document of the same file")
        return True
    if data is None:
        data = _shared.storage.get_object(storage_key)
    ranges = _ranges_of(data, document["name"])
    if ranges is None:
        _process_file(document_id, storage_key, data, document["name"])
        reuse.done(document_id, reuse.EXTRACTION)
        return True
    # The ranges are the pieces of the stage: it is complete once each is done.
    if reuse.begin(
        document_id,
        reuse.EXTRACTION,
        fingerprint,
        expected=[_range_key(first, last) for first, last in ranges],
        content_hash=content_hash,
    ):
        return True
    total, size, window = ranges[-1][1], settings.PARSE_RANGE_PAGES, max(settings.PARSE_WINDOW, 1)
    logger.info(f"{total} page(s): extracted in {len(ranges)} range(s) of {size}, {min(window, len(ranges))} at a time")
    payload = {
        "document_id": document_id,
        "collection_id": document["collection_id"],
        "storage_key": storage_key,
        "size": size,
        "total": total,
        "window": window,
        "started": time.time(),
        "parent_task_id": parent_task_id,
    }
    for first, _ in ranges[:window]:
        _spawn_range(payload, first)
    return False


def _ranges_of(data: bytes, name: str) -> list[tuple[int, int]] | None:
    """The ranges of pages a file is extracted in - None for the file that is extracted whole: one that is
    not a PDF (liteparse converts the others as a whole, each time), or no longer than a range."""
    if name.lower().endswith(_TEXT_EXTENSIONS) or _PDF_MARKER not in data[:1024]:
        return None
    total, size = _shared.count_pages(data), max(settings.PARSE_RANGE_PAGES, 1)
    if total <= size:
        return None
    return [(first, min(first + size - 1, total)) for first in range(1, total + 1, size)]


def _range_key(first: int, last: int) -> str:
    return f"pages:{first}-{last}"


def _spawn_range(payload: dict, first: int) -> None:
    _shared._spawn(
        parse_page_range,
        [{**payload, "first": first}],
        "app.tasks.parse_page_range",
        payload["document_id"],
        payload["parent_task_id"],
    )


def _process_file(document_id: str, storage_key: str, data: bytes | None = None, name: str = "") -> None:
    if data is None:
        data = _shared.storage.get_object(storage_key)
    if name.lower().endswith(_TEXT_EXTENSIONS):
        _process_markdown(document_id, data)
        return
    logger.info(f"Parsing {name or 'the file'} ({_megabytes(data)}), OCR included - a long document takes a while")
    started = time.monotonic()
    result = _shared.parse_file(data)
    logger.info(f"Parsed {len(result.pages)} page(s) in {time.monotonic() - started:.0f} s")
    # The scanned pages are read by the OCR pods, when OCR_ENGINE says so; otherwise this gives the result back.
    result = _shared.read_scanned_pages(document_id, data, result)

    def report(done: int, total: int) -> None:
        if done == total or done % max(total // 10, 1) == 0:
            logger.info(f"Stored {done}/{total} page(s) of document {document_id}")
            # Extraction is the first half of the progress bar; chunking sets the rest.
            _shared.backend_client.update_status(document_id, status="indexing", progress=done * 50 // total)

    _store_pages(document_id, result.pages, result.screenshots, report)
    # Pages are written with an upsert, so a task run twice leaves the same pages; what a previous
    # run found after the last one (#299) is dropped.
    _shared.backend_client.prune_pages(document_id, keep=max((page.page_num for page in result.pages), default=0))


def _store_pages(document_id: str, pages: list, screenshots: list, report=None) -> None:
    """The pages written to the backend, each with its screenshot stored. `report` is told how many of them
    are done, as they are."""
    screenshots_by_page = {screenshot.page_num: screenshot for screenshot in screenshots}

    def write(page) -> None:
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
            text_boxes=build_text_boxes(page),
            # The layout the OCR pods found on the page (#409). Always sent: a page read another way - by Tesseract,
            # or natively - has none, and clears what a former extraction left.
            regions=getattr(page, "layout_regions", None) or [],
            # And the tables read on it as tables (#410), for the agent to go and read. Always sent, for the same
            # reason.
            tables=getattr(page, "layout_tables", None) or [],
        )

    # Several pages at a time - 911 pages one by one, a screenshot and a request each, is minutes. Each
    # write in a copy of this context, so that its lines stay the task's (see app/task_logging.py).
    with ThreadPoolExecutor(max_workers=max(settings.PAGE_WRITE_CONCURRENCY, 1)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, write, page) for page in pages]
        for done, future in enumerate(futures, start=1):
            future.result()
            if report is not None:
                report(done, len(pages))


def _megabytes(data: bytes) -> str:
    return f"{len(data) / (1024 * 1024):.1f} MB"


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"


def _spawn_chunking(document: dict, parent_task_id: str) -> None:
    # The extraction is over, whichever branch it took: a document of a ZIP import frees its place (#335).
    _shared._extraction_done(document["id"])
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
            if _extract_file(document, self.request.id):
                _shared.backend_client.update_status(document_id, status="indexing", progress=50)
                _spawn_chunking(document, self.request.id)
    except TaskRevoked:
        raise
    except Exception as error:
        _shared.backend_client.update_status(document_id, status="error")
        _shared._fail(document_id, "extract content", error)
        raise


@celery_app.task(name="app.tasks.parse_page_range", bind=True)
def parse_page_range(self, payload: dict) -> None:
    """One range of pages of a long PDF (see the module): parsed, written, marked as a piece of the
    extraction done - with how far the document is, and what is left of it, logged. Then it starts the range
    that follows its window, and the one that completes the extraction starts the chunking."""
    document_id, total = payload["document_id"], payload["total"]
    first = payload["first"]
    last = min(first + payload["size"] - 1, total)
    try:
        logger.info(f"Parsing pages {first}-{last} of {total}")
        started = time.monotonic()
        data = _shared.storage.get_object(payload["storage_key"])
        result = _shared.parse_pages(data, first, last)
        logger.info(f"Parsed pages {first}-{last} in {_duration(time.monotonic() - started)}")
        result = _shared.read_scanned_pages(document_id, data, result)
        # A pool of threads is not the case here, but a task revoked while it parsed does not go on to
        # write, nor to start the next range.
        raise_if_revoked()
        _store_pages(document_id, result.pages, result.screenshots)
        progress = _shared.backend_client.stage_done(document_id, reuse.EXTRACTION, _range_key(first, last))
        if not progress["expected"]:
            raise RuntimeError(f"The extraction of document {document_id} was not announced in ranges")
        done, expected = progress["done"], progress["expected"]
        elapsed = time.time() - payload["started"]
        # The pace so far, so a rough estimate: a scanned page costs far more than a text one.
        left = f", about {_duration(elapsed / done * (expected - done))} left" if done < expected else ""
        logger.info(f"Extracted {done}/{expected} range(s) of {total} page(s) in {_duration(elapsed)}{left}")
        # Extraction is the first half of the progress bar; chunking sets the rest.
        _shared.backend_client.update_status(document_id, status="indexing", progress=done * 50 // expected)
        following = first + payload["window"] * payload["size"]
        if following <= total:
            _spawn_range(payload, following)
        if progress["completed_now"]:
            # What a previous, longer extraction left after the last page (#299).
            _shared.backend_client.prune_pages(document_id, keep=total)
            _spawn_chunking({"id": document_id, "collection_id": payload["collection_id"]}, payload["parent_task_id"])
    except TaskRevoked:
        raise
    except Exception as error:
        _shared.backend_client.update_status(document_id, status="error")
        _shared._fail(document_id, f"extract pages {first}-{last}", error)
        raise
