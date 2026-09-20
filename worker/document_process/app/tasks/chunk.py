"""Tâche de chunking : applique la stratégie de découpage configurée par la
collection aux pages produites par ``process_document``.

Le chunking est ce qui passe le statut à ``indexed`` — le résumé, le tagging,
la génération de QA et l'extraction d'entités tournent tous après, en
asynchrone, sans jamais le bloquer.
"""

from loguru import logger

from app.celery_app import celery_app
from app.chunking import chunk_pages
from app.task_logging import capture_task_logs
from app.tasks import _shared
from app.tasks.extract import extract_entities_window  # noqa: E402,F401
from app.tasks.qa import generate_qa_window  # noqa: E402,F401
from app.tasks.summarize import summarize_document  # noqa: E402,F401
from app.windows import sliding_windows


@celery_app.task(name="app.tasks.chunk_document", bind=True)
def chunk_document(self, document_id: str, collection_id: str) -> None:
    """Applies the collection's configured chunking strategy to the pages
    process_document wrote. Chunking is what gates "indexed" - summary,
    tagging, QA generation and entity extraction all run after this, async,
    and never block it. Summary/tagging run sequentially (tagging reads the
    summary); QA generation and entity extraction are dispatched immediately,
    one task per sliding window, so partial results stream in as they finish
    instead of waiting for the whole document."""
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            pages = _shared._get_pages(document_id)
            windows = _shared._windows(settings)
            logger.info(
                f"Chunking document {document_id} with strategy='{settings['chunking_strategy']}' "
                f"over {len(pages)} page(s)"
            )

            chunks = chunk_pages(
                pages,
                strategy=settings["chunking_strategy"],
                chunk_size=settings["chunk_size"],
                chunk_overlap=settings["chunk_overlap"],
                window_pages=windows["chunking_window_pages"],
                slide_pages=windows["chunking_slide_pages"],
            )
            logger.info(f"Produced {len(chunks)} chunk(s) for document {document_id}")
            for index, chunk in enumerate(chunks):
                # The collection's own embedding_model (unlike the collection-description
                # embedding above, chunk search never compares across collections - each one is
                # searched on its own once VDB routing has already picked it, see
                # docs/research-agent-plan.md). Best-effort: a chunk with no embedding is just
                # not searchable, it still exists for its text/summary/QA/extraction uses.
                embedding = None
                try:
                    embedding = _shared.backend_client.embed(settings["embedding_model"], chunk.text)
                except Exception:
                    logger.exception(f"Failed to embed chunk {index} of document {document_id}")

                _shared.backend_client.add_chunk(
                    document_id,
                    index=index,
                    text=chunk.text,
                    token_count=round(len(chunk.text) * _shared.TOKENS_PER_CHAR),
                    extras={"page_start": chunk.page_start, "page_end": chunk.page_end},
                    embedding=embedding,
                )

            _shared.backend_client.update_status(document_id, status="indexed", progress=100)

            parent_id = self.request.id
            _shared._spawn(
                summarize_document,
                [document_id, collection_id],
                "app.tasks.summarize_document",
                document_id,
                parent_id,
            )

            total_pages = len(pages)
            for start, end in sliding_windows(total_pages, windows["qa_window_pages"], windows["qa_slide_pages"]):
                _shared._spawn(
                    generate_qa_window,
                    [
                        document_id,
                        collection_id,
                        start,
                        end,
                        windows["qa_questions_per_window"],
                    ],
                    "app.tasks.generate_qa_window",
                    document_id,
                    parent_id,
                )
            for start, end in sliding_windows(
                total_pages,
                windows["extraction_window_pages"],
                windows["extraction_slide_pages"],
            ):
                _shared._spawn(
                    extract_entities_window,
                    [document_id, collection_id, start, end],
                    "app.tasks.extract_entities_window",
                    document_id,
                    parent_id,
                )
        except Exception as error:
            _shared.backend_client.update_status(document_id, status="error")
            _shared._fail(document_id, "chunk", error)
            raise
