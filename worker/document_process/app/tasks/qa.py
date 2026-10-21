"""Tâches de génération de paires question/réponse.

- ``generate_qa_window`` : génère des QA ancrées dans une fenêtre de pages
  du document (pipeline classique).
- ``generate_collection_qa`` : génère des QA au niveau de la collection,
  ancrées dans la description de la collection plutôt que dans un document.
"""

from loguru import logger

from app.celery_app import celery_app
from app.chunking import PageText
from app.task_logging import capture_task_logs
from app.tasks import _shared


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def locate_evidence(pages: list[PageText], quote: str) -> tuple[int, str] | None:
    """The page a quote the LLM gave as evidence really is on, with the quote itself (#126). Only a
    passage found word for word in the text counts - an invented or reworded one is dropped (the
    backend then finds the passage on its own), so a source shown to the user is never made up."""
    wanted = _squash(quote)
    if len(wanted) < 15:
        return None
    for page in pages:
        if wanted in _squash(page.content):
            return page.page_number, " ".join(quote.split())
    return None


@celery_app.task(name="app.tasks.generate_qa_window", bind=True)
def generate_qa_window(self, document_id: str, collection_id: str, start_page: int, end_page: int, k: int) -> None:
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "qa")
            if model is None:
                logger.warning(f"No QA model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("qa", "")
            pages = _shared._get_pages(document_id)
            text = _shared._window_text(pages, start_page, end_page)
            logger.info(f"Generating {k} QA pair(s) for document {document_id}, pages {start_page}-{end_page}")

            pairs = _shared._chat_json(
                model,
                f"{instructions}\nGenerate exactly {k} question/answer pairs grounded strictly in the given text. "
                'Respond only with a JSON array of {"question": ..., "answer": ..., "evidence": ...} objects, '
                "where evidence is the exact passage of the text (copied word for word, one or two sentences) "
                "that the answer comes from.".strip(),
                text,
            )
            if not isinstance(pairs, list):
                raise ValueError(f"Expected a JSON array of QA pairs, got: {pairs!r}")

            logger.info(f"Generated {len(pairs)} QA pair(s) for pages {start_page}-{end_page}")
            window_pages = [page for page in pages if start_page <= page.page_number <= end_page]
            for pair in pairs:
                question, answer = str(pair["question"]), str(pair["answer"])
                # Best-effort, same fail-soft reasoning as a chunk's own embedding above: a QA
                # pair with no embedding still exists and still answers via the normal QA list,
                # it's just never surfaced by the research agent's QA-first retrieval tier.
                embedding = None
                try:
                    embedding = _shared.backend_client.embed(settings["embedding_model"], question)
                except Exception:
                    logger.exception(f"Failed to embed QA question for document {document_id}")
                source = locate_evidence(window_pages, str(pair.get("evidence") or ""))
                _shared.backend_client.create_qa_pair(
                    collection_id,
                    document_id,
                    question,
                    answer,
                    embedding,
                    source_page=source[0] if source else None,
                    source_excerpt=source[1] if source else None,
                )
        except Exception as error:
            _shared._fail(document_id, f"generate QA for pages {start_page}-{end_page}", error)
            raise


@celery_app.task(name="app.tasks.generate_collection_qa", bind=True)
def generate_collection_qa(self, document_id: str, collection_id: str, description: str) -> None:
    """Generates a handful of reference QA pairs grounded in the collection's
    description rather than any one document - see document_id=None on
    QaPairCreate, the same nullable field a manually-added QA pair uses.
    Only dispatched when update_collection_description just changed the
    description; existing collection-level QA pairs are left in place
    (accumulated, not replaced) since older ones can still be valid."""
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "qa")
            if model is None:
                logger.warning(f"No QA model available for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("qa", "")
            count = _shared._windows(settings)["collection_qa_count"]
            prompt = (
                f"{instructions}\nGenerate exactly {count} question/answer pairs about this document collection, "
                "grounded strictly in the given description. Respond only with a JSON array of "
                '{"question": ..., "answer": ...} objects.'
            ).strip()
            pairs = _shared._chat_json(model, prompt, description)
            if not isinstance(pairs, list):
                raise ValueError(f"Expected a JSON array of QA pairs, got: {pairs!r}")

            for pair in pairs:
                question, answer = str(pair["question"]), str(pair["answer"])
                embedding = None
                try:
                    embedding = _shared.backend_client.embed(settings["embedding_model"], question)
                except Exception:
                    logger.exception(f"Failed to embed collection-level QA question for collection {collection_id}")
                _shared.backend_client.create_qa_pair(collection_id, None, question, answer, embedding)
            logger.info(f"Generated {len(pairs)} collection-level QA pair(s) for collection {collection_id}")
        except Exception as error:
            _shared._fail(document_id, "generate collection-level QA pairs", error)
            raise
