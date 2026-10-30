"""Tâches des fichiers copiés d'un autre système (#457).

Muffin ne traite pas ces fichiers - texte, chunks et vecteurs viennent de l'autre système - mais leur donne ce que
sa recherche et son routage attendent : un résumé par fichier, puis la description de la collection, indexée pour
qu'une question puisse y mener. Lancées par le backend après chaque synchronisation, avec la priorité la plus basse.

- ``summarize_copied_document`` : résumé d'un fichier copié, à partir de son texte découpé en pages fictives.
- ``describe_copied_collection`` : met à jour la description de la collection avec ce résumé.
"""

from loguru import logger

from app.celery_app import celery_app
from app.chunking import PageText
from app.config import settings as worker_settings
from app.tasks import _shared
from app.tasks.collection import _maintain_description
from app.tasks.summarize import _summarize

# Celery's lowest priority, what the backend sends the task with (BULK_PRIORITY): the next task goes the same way.
LOW_PRIORITY = 9


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
    twice, or for a file that did not change, costs nothing. Then sends the update of the collection's description."""
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
        _shared._spawn(
            describe_copied_collection,
            [document_id, collection_id],
            "app.tasks.describe_copied_collection",
            document_id,
            self.request.id,
            priority=LOW_PRIORITY,
        )
    except Exception as error:
        _shared._fail(document_id, "summarize", error)
        raise


@celery_app.task(name="app.tasks.describe_copied_collection", bind=True)
def describe_copied_collection(self, document_id: str, collection_id: str) -> None:
    """The collection's description, brought up to date with the summary just made: made from the summaries of its
    files when it has none, otherwise kept unless the model says this summary changes it. Its embedding goes to the
    index that routes a question to a collection, including a description that stays when it was never put there -
    the one the other system gave. No QA pairs of the collection, which are Muffin's pipeline."""
    try:
        _maintain_description(document_id, collection_id, index_unchanged=True)
    except Exception as error:
        _shared._fail(document_id, "update the collection description", error)
        raise
