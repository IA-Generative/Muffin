"""Scheduled refresh of URL documents (#19).

On the hour and at half past, the beat sends ``scan_url_refresh``: it asks the backend which URL
documents are due (each one is claimed once, its next run moved forward) and sends one
``refresh_url_document`` per document. That task fetches the page again and reports its hash - of
its text for an HTML page, of the file itself for a URL serving one: when it differs from what is
indexed, the backend reprocesses the document from scratch - this worker's usual
``process_document`` pipeline, which replaces summary, chunks, embeddings, QA, entities and tags.
An unchanged page costs one fetch and nothing else.
"""

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared


@celery_app.task(name="app.tasks.scan_url_refresh")
def scan_url_refresh() -> int:
    document_ids = _shared.backend_client.claim_url_refresh()
    for document_id in document_ids:
        refresh_url_document.apply_async(args=[document_id])
    if document_ids:
        logger.info(f"URL refresh: {len(document_ids)} document(s) due")
    return len(document_ids)


@celery_app.task(name="app.tasks.refresh_url_document")
def refresh_url_document(document_id: str) -> bool:
    """Returns whether the page changed. A page that can't be fetched right now (site down, timeout)
    is only logged: the document keeps what it has, and the next run tries again."""
    document = _shared.backend_client.get_document(document_id)
    if document["type"] != "url":
        return False
    try:
        fetched = _shared.fetch_url(document["name"])
    except Exception:
        logger.exception(f"URL refresh: could not fetch {document['name']} for document {document_id}")
        return False
    changed = _shared.backend_client.report_url_fetch(document_id, fetched.content_hash)
    logger.info(f"URL refresh of document {document_id}: {'changed, reprocessing' if changed else 'unchanged'}")
    return changed
