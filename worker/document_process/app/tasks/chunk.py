"""Tâche de chunking : applique la stratégie de découpage configurée par la
collection aux pages produites par ``process_document``.

Le chunking est ce qui passe le statut à ``indexed`` — le résumé, le tagging,
la génération de QA et l'extraction d'entités tournent tous après, en
asynchrone, sans jamais le bloquer.
"""

from loguru import logger

from app import reuse
from app.celery_app import celery_app
from app.chunking import chunk_pages
from app.tasks import _shared
from app.tasks.extract import extract_entities_window  # noqa: E402,F401
from app.tasks.qa import generate_qa_window  # noqa: E402,F401
from app.tasks.summarize import summarize_document  # noqa: E402,F401
from app.windows import sliding_windows


def _reused_windows(
    document_id: str,
    content_hash: str | None,
    settings: dict,
    stage: str,
    step: str,
    windows: list[tuple[int, int]],
    key_prefix: str,
) -> bool:
    """Whether a stage run in windows of pages (the QA pairs, the entities) is reused from another
    document of the same file (#300) - then no window is spawned. Otherwise the stage is announced with
    its windows, and is complete once each has been written (the backend notes it as they are)."""
    model = _shared._model_for(settings, step)
    if not content_hash or model is None or not windows:
        return False
    fingerprint = (reuse.qa if stage == reuse.QA else reuse.entities)(content_hash, settings, model)
    return reuse.begin(
        document_id, stage, fingerprint, expected=[f"{key_prefix}:{start}-{end}" for start, end in windows]
    )


@celery_app.task(name="app.tasks.chunk_document", bind=True)
def chunk_document(
    self,
    document_id: str,
    collection_id: str,
    skip_summary: bool = False,
    skip_qa: bool = False,
    skip_chunking: bool = False,
    skip_extraction: bool = False,
) -> None:
    """Applies the collection's configured chunking strategy to the pages
    process_document wrote. Chunking is what gates "indexed" - summary,
    tagging, QA generation and entity extraction all run after this, async,
    and never block it. Summary/tagging run sequentially (tagging reads the
    summary); QA generation and entity extraction are dispatched immediately,
    one task per sliding window, so partial results stream in as they finish
    instead of waiting for the whole document.

    ``skip_summary`` and ``skip_qa`` are used by the tabular pipeline, which
    generates its own summary and QA from the tabular profile (more compact
    and relevant than a CSV dump) before calling chunk_document. The tabular
    pipeline still uses the same LLM calls (``_shared._chat``) and the same
    persistence (``set_document_summary``, ``replace_generated_qa``) as the classic
    tasks — only the prompt differs.

    ``skip_chunking`` is also used by the tabular pipeline: a CSV dump chunked
    into text is not useful for vector search (the Parquet export + profile
    already cover data access), so the tabular pipeline skips chunking
    entirely and goes straight to "indexed".

    ``skip_extraction`` is also used by the tabular pipeline: entity extraction
    on raw CSV rows is slow (LLM per window) and low-value for tabular data
    where the profile already captures the structure. The tabular pipeline
    skips it entirely."""
    try:
        settings = _shared.backend_client.get_collection_settings(collection_id)
        pages = _shared._get_pages(document_id)
        windows = _shared._windows(settings)
        logger.info(
            f"Chunking document {document_id} with strategy='{settings['chunking_strategy']}' over {len(pages)} page(s)"
        )

        content_hash = (
            reuse.valid_hash(_shared.backend_client.get_document(document_id).get("content_hash"))
            if not (skip_chunking and skip_qa and skip_extraction)
            else None
        )

        if not skip_chunking:
            # The chunks of another document of the same file, if its settings were the same (#300):
            # copied with their vectors, nothing is cut or embedded here.
            fingerprint = reuse.chunks(content_hash, settings) if content_hash else None
            if reuse.begin(document_id, reuse.CHUNKS, fingerprint):
                logger.info(f"Chunks of document {document_id} reused")
            else:
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
                        extras={
                            "page_start": chunk.page_start,
                            "page_end": chunk.page_end,
                        },
                        embedding=embedding,
                    )
                # Chunks are written with an upsert on their position, so a task run twice leaves the
                # same ones; what a previous run cut after the last one goes, with its vectors (#299).
                _shared.backend_client.prune_chunks(document_id, keep=len(chunks))
                reuse.done(document_id, reuse.CHUNKS)
        else:
            logger.info(f"Skipping chunking for document {document_id} (tabular pipeline)")

        _shared.backend_client.update_status(document_id, status="indexed", progress=100)

        parent_id = self.request.id
        if not skip_summary:
            _shared._spawn(
                summarize_document,
                [document_id, collection_id],
                "app.tasks.summarize_document",
                document_id,
                parent_id,
            )

        total_pages = len(pages)
        qa_windows = list(sliding_windows(total_pages, windows["qa_window_pages"], windows["qa_slide_pages"]))
        if not skip_qa and not _reused_windows(
            document_id, content_hash, settings, reuse.QA, "qa", qa_windows, "window"
        ):
            for start, end in qa_windows:
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
        extraction_windows = list(
            sliding_windows(total_pages, windows["extraction_window_pages"], windows["extraction_slide_pages"])
        )
        if not skip_extraction and not _reused_windows(
            document_id, content_hash, settings, reuse.ENTITIES, "extraction", extraction_windows, "pages"
        ):
            for start, end in extraction_windows:
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
