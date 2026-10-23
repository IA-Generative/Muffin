"""Tâche de chunking : applique la stratégie de découpage configurée par la
collection aux pages produites par ``process_document``.

Le chunking est ce qui passe le statut à ``indexed`` — le résumé, le tagging,
la génération de QA et l'extraction d'entités tournent tous après, en
asynchrone, sans jamais le bloquer.
"""

from loguru import logger

from app import reuse, sampling
from app.backend_client import Embedding
from app.celery_app import celery_app
from app.chunking import Chunk, ChunkStarts, chunk_pages
from app.config import settings as worker_settings
from app.task_revocation import TaskRevoked, raise_if_revoked
from app.tasks import _shared
from app.tasks.extract import extract_entities_window  # noqa: E402,F401
from app.tasks.qa import generate_qa_window  # noqa: E402,F401
from app.tasks.summarize import summarize_document  # noqa: E402,F401


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


def _prune_windows(document_id: str, **keep: list[str]) -> None:
    """Best-effort: what is left of windows no longer read is stale data, never worth failing the document over."""
    try:
        _shared.backend_client.prune_windows(document_id, **keep)
    except Exception:
        logger.exception(f"Could not remove what earlier runs derived from the windows no longer read ({document_id})")


def _announce_windows(
    document_id: str, step: str, windows: list[tuple[int, int]], total_pages: int, drawn: bool
) -> None:
    """The log line that says what a long document is read of: windows drawn out of it, or all of them."""
    if drawn:
        logger.info(
            f"Long document {document_id} ({total_pages} pages): {step} read on {len(windows)} window(s) drawn over it"
        )


def _llm_chunk_starts(settings: dict) -> ChunkStarts | None:
    """How the "llm" strategy asks the collection's chunking model (or the hub's default one) where its
    chunks begin - None, the document cut by paragraph, without any. The model sees the paragraphs
    numbered and answers with numbers only: it never writes the chunks' text."""
    if settings["chunking_strategy"] != "llm":
        return None
    model = _shared._model_for(settings, "chunking")
    if model is None:
        logger.warning("LLM chunking without any chat model available: cut by paragraph")
        return None
    instructions = settings["instructions"].get("chunking", "")
    system = (
        f"{instructions}\nYou split a document into chunks for semantic search. You are given its paragraphs, "
        "numbered from 0, in order. Group consecutive paragraphs into chunks that each cover one topic and can "
        "be understood on their own - typically a few paragraphs, 100 to 400 words; a heading always starts a "
        "chunk with what follows it. Respond only with a JSON array of the numbers of the paragraphs that start "
        "a chunk, in increasing order, starting with 0."
    ).strip()

    def chunk_starts(paragraphs: list[str]) -> list[int]:
        numbered = "\n\n".join(f"[{index}] {paragraph}" for index, paragraph in enumerate(paragraphs))
        return _shared._chat_json(model, system, numbered)

    return chunk_starts


def _embed_all(model: str, chunks: list[Chunk], document_id: str) -> list[Embedding | None]:
    """The chunks' vectors, EMBED_BATCH_SIZE to a call. A batch the hub refuses is done again one chunk at
    a time, so that a single bad chunk costs its own vector only. Best-effort: a chunk with no embedding
    is just not searchable, it still exists for its text/summary/QA/extraction uses."""
    embeddings: list[Embedding | None] = []
    size = max(worker_settings.EMBED_BATCH_SIZE, 1)
    for start in range(0, len(chunks), size):
        # A batch is an embedding call: where a task in a pool of threads, which Celery cannot kill,
        # notices it was revoked.
        raise_if_revoked()
        texts = [chunk.text for chunk in chunks[start : start + size]]
        try:
            vectors = list(_shared.backend_client.embed_batch(model, texts))
            if len(vectors) != len(texts):
                raise ValueError(f"{len(vectors)} vector(s) for {len(texts)} text(s)")
            embeddings.extend(Embedding(vector, model) for vector in vectors)
        except Exception:
            logger.exception(
                f"Failed to embed chunks {start}-{start + len(texts) - 1} of document {document_id} at once"
            )
            for offset, text in enumerate(texts):
                try:
                    embeddings.append(_shared.backend_client.embed(model, text))
                except Exception:
                    logger.exception(f"Failed to embed chunk {start + offset} of document {document_id}")
                    embeddings.append(None)
        _log_progress("Embedded", len(embeddings), len(chunks), "chunk(s)", document_id)
    return embeddings


def _log_progress(what: str, done: int, total: int, unit: str, document_id: str) -> None:
    """About ten lines however long the document: a long one shows it is moving, a short one stays quiet."""
    step = max(total // 10, 1)
    if done == total or done // step != (done - 1) // step:
        logger.info(f"{what} {done}/{total} {unit} of document {document_id}")


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
                    chunk_starts=_llm_chunk_starts(settings),
                    concurrency=worker_settings.CHUNKING_LLM_CONCURRENCY,
                )
                logger.info(f"Produced {len(chunks)} chunk(s) for document {document_id}")
                # The collection's own embedding_model (unlike the collection-description embedding,
                # chunk search never compares across collections - each one is searched on its own once
                # VDB routing has already picked it, see docs/research-agent-plan.md).
                embeddings = _embed_all(settings["embedding_model"], chunks, document_id)
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                    _shared.backend_client.add_chunk(
                        document_id,
                        index=index,
                        text=chunk.text,
                        token_count=round(len(chunk.text) * _shared.TOKENS_PER_CHAR),
                        extras={
                            "page_start": chunk.page_start,
                            "page_end": chunk.page_end,
                            # Where the chunk is in each page it touches (#353).
                            "spans": chunk.spans,
                        },
                        embedding=embedding,
                    )
                    _log_progress("Stored", index + 1, len(chunks), "chunk(s)", document_id)
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
        pages_text = {page.page_number: page.content for page in pages}
        # What a long document is read of (#372): every window until a collection says otherwise - and the same
        # windows for the same file, whichever document it is.
        qa_windows, questions_per_window, qa_drawn = sampling.plan_qa(
            total_pages, windows, pages_text, sampling.seed_for(document_id, content_hash, "qa")
        )
        if not skip_qa and not _reused_windows(
            document_id, content_hash, settings, reuse.QA, "qa", qa_windows, "window"
        ):
            _announce_windows(document_id, "QA", qa_windows, len(pages), qa_drawn)
            # What an earlier run under other settings made of windows that are no longer read goes. When every window
            # is read there is nothing of the sort.
            if qa_drawn:
                _prune_windows(document_id, qa=[f"window:{start}-{end}" for start, end in qa_windows])
            _shared.start_lanes(
                generate_qa_window,
                "app.tasks.generate_qa_window",
                document_id,
                collection_id,
                qa_windows,
                (total_pages, windows["qa_window_pages"], windows["qa_slide_pages"]),
                [questions_per_window],
                parent_id,
                drawn=qa_drawn,
            )
        extraction_windows, extraction_drawn = sampling.plan_entities(
            total_pages, windows, pages_text, sampling.seed_for(document_id, content_hash, "entities")
        )
        if not skip_extraction and not _reused_windows(
            document_id, content_hash, settings, reuse.ENTITIES, "extraction", extraction_windows, "pages"
        ):
            _announce_windows(document_id, "entities", extraction_windows, len(pages), extraction_drawn)
            if extraction_drawn:
                _prune_windows(document_id, entities=[f"pages:{start}-{end}" for start, end in extraction_windows])
            _shared.start_lanes(
                extract_entities_window,
                "app.tasks.extract_entities_window",
                document_id,
                collection_id,
                extraction_windows,
                (total_pages, windows["extraction_window_pages"], windows["extraction_slide_pages"]),
                [],
                parent_id,
                drawn=extraction_drawn,
            )
    except TaskRevoked:
        raise
    except Exception as error:
        _shared.backend_client.update_status(document_id, status="error")
        _shared._fail(document_id, "chunk", error)
        raise
