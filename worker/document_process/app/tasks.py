from loguru import logger

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.parsing import parse_file
from app.scraping import fetch_url_markdown
from app.storage import storage

TOKENS_PER_CHAR = 0.25  # rough estimate, good enough until a real tokenizer is wired in


def _process_url(document_id: str, url: str) -> None:
    markdown = fetch_url_markdown(url)
    backend_client.add_page(document_id, page_number=1, content=markdown)
    backend_client.add_chunk(document_id, index=0, text=markdown, token_count=round(len(markdown) * TOKENS_PER_CHAR))


def _process_file(document_id: str, storage_key: str) -> None:
    data = storage.get_object(storage_key)
    result = parse_file(data)

    screenshots_by_page = {screenshot.page_num: screenshot for screenshot in result.screenshots}

    chunk_index = 0
    for page in result.pages:
        screenshot_key: str | None = None
        screenshot = screenshots_by_page.get(page.page_num)
        if screenshot is not None:
            screenshot_key = f"screenshots/{document_id}/page-{page.page_num}.png"
            storage.put_object(screenshot_key, screenshot.image_bytes, content_type="image/png")

        backend_client.add_page(document_id, page_number=page.page_num, content=page.text, screenshot=screenshot_key)

        for block in page.blocks or []:
            if not block.text:
                continue
            extras = {
                "kind": block.kind,
                "page": page.page_num,
                "bbox": (
                    {"x": block.bbox.x, "y": block.bbox.y, "width": block.bbox.width, "height": block.bbox.height}
                    if block.bbox
                    else None
                ),
            }
            backend_client.add_chunk(
                document_id,
                index=chunk_index,
                text=block.text,
                token_count=round(len(block.text) * TOKENS_PER_CHAR),
                extras=extras,
            )
            chunk_index += 1


@celery_app.task(name="app.tasks.process_document")
def process_document(document_id: str) -> None:
    """Entry point: fetch the document's metadata, extract its content
    (scraping for URLs, liteparse for uploaded files), and write pages/chunks
    back to the backend. Chunking is what gates "indexed" - entity/relation
    extraction, QA generation, tagging and summarization are a separate,
    async phase that reads these chunks once they exist."""
    try:
        document = backend_client.get_document(document_id)
        backend_client.update_status(document_id, status="indexing", progress=0)

        if document["type"] == "url":
            _process_url(document_id, document["name"])
        else:
            if not document["storage_key"]:
                raise ValueError(f"Document {document_id} has no storage_key to fetch from RustFS")
            _process_file(document_id, document["storage_key"])

        backend_client.update_status(document_id, status="indexed", progress=100)
    except Exception as error:
        logger.exception(f"Failed to process document {document_id}")
        try:
            backend_client.update_status(document_id, status="error", summary=str(error))
        except Exception:
            logger.exception(f"Also failed to report the error for document {document_id} back to the backend")
        raise
