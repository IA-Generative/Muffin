"""Tâches des fichiers copiés d'un autre système (#457).

Muffin ne traite pas ces fichiers - texte, chunks et vecteurs viennent de l'autre système - mais leur donne le
résumé que sa recherche attend. Lancée par la synchronisation, avec la priorité la plus basse.

- ``summarize_copied_document`` : résumé d'un fichier copié, à partir de son texte découpé en pages fictives.
"""

from loguru import logger

from app.celery_app import celery_app
from app.chunking import PageText
from app.config import settings as worker_settings
from app.tasks import _shared
from app.tasks.summarize import _summarize


def fictional_pages(text: str, words_per_page: int) -> list[PageText]:
    """The text cut into pages of `words_per_page` words, numbered from 1. They exist only for the summary, which
    reads by pages: the document keeps its own, and nothing records or cites these."""
    words = text.split()
    size = max(words_per_page, 1)
    return [
        PageText(page_number=number, content=" ".join(words[start : start + size]))
        for number, start in enumerate(range(0, len(words), size), start=1)
    ]


@celery_app.task(name="app.tasks.summarize_copied_document", bind=True)
def summarize_copied_document(self, document_id: str, collection_id: str) -> None:
    """Summarizes a copied file as Muffin does its own - the collection's model and instructions, a partial summary
    per batch of `summary_pages_per_map` pages, then their combination - and stores it with its vector, in the index
    of the collection's embedding model (the other system's). A file that has a summary is left alone, so a task sent
    twice, or for a file that did not change, costs nothing."""
    try:
        document = _shared.backend_client.get_document(document_id)
        if document.get("summary"):
            logger.info(f"Document {document_id} already has a summary, nothing to do")
            return
        settings = _shared.backend_client.get_collection_settings(collection_id)
        model = _shared._model_for(settings, "summary")
        if model is None:
            logger.warning(f"No summary model configured for collection {collection_id}, skipping")
            return
        text = "\n\n".join(page.content for page in _shared._get_pages(document_id))
        pages = fictional_pages(text, worker_settings.SYNC_SUMMARY_WORDS_PER_PAGE)
        if not pages:
            logger.info(f"Document {document_id} has no text to summarize")
            return
        _summarize(document_id, settings, model, pages)
    except Exception as error:
        _shared._fail(document_id, "summarize", error)
        raise
