import json
from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.celery_app import celery_app
from app.chunking import PageText, chunk_pages
from app.parsing import parse_file
from app.scraping import fetch_url_markdown
from app.storage import storage
from app.task_logging import capture_task_logs
from app.windows import sliding_windows

TOKENS_PER_CHAR = 0.25  # rough estimate, good enough until a real tokenizer is wired in

# Mirrors app/schemas/collection.py's PipelineWindowsOut defaults - the
# collection settings endpoint only returns the keys the user actually
# overrode, missing keys fall back to these.
PIPELINE_WINDOW_DEFAULTS = {
    "summary_pages_per_map": 5,
    "qa_window_pages": 2,
    "qa_slide_pages": 1,
    "qa_questions_per_window": 3,
    "extraction_window_pages": 4,
    "extraction_slide_pages": 1,
    "chunking_window_pages": 2,
    "chunking_slide_pages": 1,
    "collection_qa_count": 3,
}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    lines = lines[1:] if lines else lines
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _windows(settings: dict[str, Any]) -> dict[str, int]:
    return {**PIPELINE_WINDOW_DEFAULTS, **(settings.get("pipeline_windows") or {})}


def _model_for(settings: dict[str, Any], step: str) -> str | None:
    """Falls back to the LLM hub's first available chat model when this step
    has none configured, so a fresh collection's pipeline works out of the
    box instead of silently skipping every generation step until someone
    visits Paramètres and saves a model for each one."""
    configured = (settings.get("generation_models") or {}).get(step)
    return configured or backend_client.get_default_chat_model()


def _spawn(task, args: list[Any], task_name: str, document_id: str, parent_task_id: str | None) -> None:
    result = task.apply_async(args=args)
    backend_client.create_task(result.id, task_name, document_id, parent_celery_task_id=parent_task_id)


def _chat(model: str, system: str, user_content: str) -> str:
    messages = (
        [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
        if system
        else [{"role": "user", "content": user_content}]
    )
    return backend_client.llm_chat(model, messages)


def _chat_json(model: str, system: str, user_content: str) -> Any:
    raw = _chat(model, system, user_content)
    cleaned = _strip_code_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        logger.error(f"Model '{model}' returned invalid JSON ({len(raw)} chars, starts with: {raw[:200]!r})")
        raise ValueError(f"Model '{model}' returned invalid JSON") from error


def _batches(pages: list[PageText], size: int) -> list[list[PageText]]:
    size = max(size, 1)
    return [pages[i : i + size] for i in range(0, len(pages), size)]


def _window_text(pages: list[PageText], start_page: int, end_page: int) -> str:
    return "\n\n".join(page.content for page in pages if start_page <= page.page_number <= end_page)


def _get_pages(document_id: str) -> list[PageText]:
    return [PageText(page_number=p["page_number"], content=p["content"]) for p in backend_client.get_pages(document_id)]


def _process_url(document_id: str, url: str) -> None:
    markdown = fetch_url_markdown(url)
    backend_client.add_page(document_id, page_number=1, content=markdown)


def _process_file(document_id: str, storage_key: str) -> None:
    data = storage.get_object(storage_key)
    result = parse_file(data)
    screenshots_by_page = {screenshot.page_num: screenshot for screenshot in result.screenshots}

    for page in result.pages:
        screenshot_key: str | None = None
        screenshot = screenshots_by_page.get(page.page_num)
        if screenshot is not None:
            screenshot_key = f"screenshots/{document_id}/page-{page.page_num}.png"
            storage.put_object(screenshot_key, screenshot.image_bytes, content_type="image/png")
        backend_client.add_page(document_id, page_number=page.page_num, content=page.text, screenshot=screenshot_key)


def _fail(document_id: str, task_label: str, error: Exception) -> None:
    logger.exception(f"Failed to {task_label} for document {document_id}")
    try:
        backend_client.set_document_error(document_id, str(error))
    except Exception:
        logger.exception(f"Also failed to report the error for document {document_id} back to the backend")


@celery_app.task(name="app.tasks.process_document", bind=True)
def process_document(self, document_id: str) -> None:
    """Entry point: extract raw content (scraping for URLs, liteparse for
    uploaded files) and write pages back to the backend. No chunking here -
    that's chunk_document's job, so it can apply the collection's configured
    strategy instead of liteparse's raw layout blocks."""
    with capture_task_logs(self.request.id):
        try:
            document = backend_client.get_document(document_id)
            logger.info(f"Processing document {document_id} ({document['type']}): {document['name']}")
            backend_client.update_status(document_id, status="indexing", progress=0)

            if document["type"] == "url":
                _process_url(document_id, document["name"])
            else:
                if not document["storage_key"]:
                    raise ValueError(f"Document {document_id} has no storage_key to fetch from RustFS")
                _process_file(document_id, document["storage_key"])

            page_count = len(backend_client.get_pages(document_id))
            logger.info(f"Extracted {page_count} page(s) for document {document_id}")
            backend_client.update_status(document_id, status="indexing", progress=50)
            _spawn(
                chunk_document,
                [document_id, document["collection_id"]],
                "app.tasks.chunk_document",
                document_id,
                self.request.id,
            )
        except Exception as error:
            backend_client.update_status(document_id, status="error")
            _fail(document_id, "extract content", error)
            raise


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
            settings = backend_client.get_collection_settings(collection_id)
            pages = _get_pages(document_id)
            windows = _windows(settings)
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
                backend_client.add_chunk(
                    document_id,
                    index=index,
                    text=chunk.text,
                    token_count=round(len(chunk.text) * TOKENS_PER_CHAR),
                    extras={"page_start": chunk.page_start, "page_end": chunk.page_end},
                )

            backend_client.update_status(document_id, status="indexed", progress=100)

            parent_id = self.request.id
            _spawn(
                summarize_document,
                [document_id, collection_id],
                "app.tasks.summarize_document",
                document_id,
                parent_id,
            )

            total_pages = len(pages)
            for start, end in sliding_windows(total_pages, windows["qa_window_pages"], windows["qa_slide_pages"]):
                _spawn(
                    generate_qa_window,
                    [document_id, collection_id, start, end, windows["qa_questions_per_window"]],
                    "app.tasks.generate_qa_window",
                    document_id,
                    parent_id,
                )
            for start, end in sliding_windows(
                total_pages, windows["extraction_window_pages"], windows["extraction_slide_pages"]
            ):
                _spawn(
                    extract_entities_window,
                    [document_id, collection_id, start, end],
                    "app.tasks.extract_entities_window",
                    document_id,
                    parent_id,
                )
        except Exception as error:
            backend_client.update_status(document_id, status="error")
            _fail(document_id, "chunk", error)
            raise


@celery_app.task(name="app.tasks.summarize_document", bind=True)
def summarize_document(self, document_id: str, collection_id: str) -> None:
    """Map-reduce: one partial summary per batch of `summary_pages_per_map`
    pages (map), then a final pass combining those partials (reduce). On
    success, dispatches tag_document (reads this summary), plus
    update_collection_description and update_collection_tags - both decide
    for themselves whether the collection's description/tags actually need
    to change given this new summary."""
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "summary")
            if model is None:
                logger.warning(f"No summary model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("summary", "")
            pages = _get_pages(document_id)
            pages_per_map = _windows(settings)["summary_pages_per_map"]
            logger.info(f"Summarizing document {document_id}: {len(pages)} page(s), {pages_per_map} page(s) per map")

            partials = [
                _chat(
                    model,
                    f"{instructions}\nSummarize the following excerpt concisely.".strip(),
                    "\n\n".join(page.content for page in batch),
                )
                for batch in _batches(pages, pages_per_map)
            ]

            if len(partials) == 1:
                summary = partials[0]
            else:
                summary = _chat(
                    model,
                    f"{instructions}\nCombine the following partial summaries into one coherent summary.".strip(),
                    "\n\n---\n\n".join(partials),
                )

            backend_client.set_document_summary(document_id, summary)
            logger.info(f"Summary for document {document_id} saved ({len(summary)} chars)")

            parent_id = self.request.id
            _spawn(tag_document, [document_id, collection_id], "app.tasks.tag_document", document_id, parent_id)
            _spawn(
                update_collection_description,
                [document_id, collection_id],
                "app.tasks.update_collection_description",
                document_id,
                parent_id,
            )
            _spawn(
                update_collection_tags,
                [document_id, collection_id],
                "app.tasks.update_collection_tags",
                document_id,
                parent_id,
            )
        except Exception as error:
            _fail(document_id, "summarize", error)
            raise


@celery_app.task(name="app.tasks.tag_document", bind=True)
def tag_document(self, document_id: str, collection_id: str) -> None:
    """Reads the summary summarize_document just produced (falling back to
    the first page if there isn't one yet) and asks for a short list of
    tags."""
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "tagging")
            if model is None:
                logger.warning(f"No tagging model configured for collection {collection_id}, skipping")
                return

            document = backend_client.get_document(document_id)
            instructions = settings["instructions"].get("tagging", "")
            content = document.get("summary") or "\n\n".join(page.content for page in _get_pages(document_id)[:1])

            prompt = f"{instructions}\nRespond only with a JSON array of short, lowercase tag strings (no more than 8)."
            tags = _chat_json(model, prompt.strip(), content)
            if not isinstance(tags, list):
                raise ValueError(f"Expected a JSON array of tags, got: {tags!r}")

            backend_client.replace_document_tags(document_id, [str(tag) for tag in tags])
            logger.info(f"Saved {len(tags)} tag(s) for document {document_id}")
        except Exception as error:
            _fail(document_id, "tag", error)
            raise


@celery_app.task(name="app.tasks.generate_qa_window", bind=True)
def generate_qa_window(self, document_id: str, collection_id: str, start_page: int, end_page: int, k: int) -> None:
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "qa")
            if model is None:
                logger.warning(f"No QA model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("qa", "")
            text = _window_text(_get_pages(document_id), start_page, end_page)
            logger.info(f"Generating {k} QA pair(s) for document {document_id}, pages {start_page}-{end_page}")

            pairs = _chat_json(
                model,
                f"{instructions}\nGenerate exactly {k} question/answer pairs grounded strictly in the given text. "
                'Respond only with a JSON array of {"question": ..., "answer": ...} objects.'.strip(),
                text,
            )
            if not isinstance(pairs, list):
                raise ValueError(f"Expected a JSON array of QA pairs, got: {pairs!r}")

            logger.info(f"Generated {len(pairs)} QA pair(s) for pages {start_page}-{end_page}")
            for pair in pairs:
                backend_client.create_qa_pair(collection_id, document_id, str(pair["question"]), str(pair["answer"]))
        except Exception as error:
            _fail(document_id, f"generate QA for pages {start_page}-{end_page}", error)
            raise


@celery_app.task(name="app.tasks.extract_entities_window", bind=True)
def extract_entities_window(self, document_id: str, collection_id: str, start_page: int, end_page: int) -> None:
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "extraction")
            if model is None:
                logger.warning(f"No extraction model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("extraction", "")
            text = _window_text(_get_pages(document_id), start_page, end_page)
            logger.info(f"Extracting entities/relations for document {document_id}, pages {start_page}-{end_page}")

            prompt = (
                f"{instructions}\nExtract named entities (type one of: personne, organisation, lieu, date, autre) "
                "and the relations between them from the given text. Respond only with JSON: "
                '{"entities": [{"name": ..., "type": ...}], "relations": [{"from": ..., "to": ..., "type": ...}]}.'
            )
            result = _chat_json(model, prompt.strip(), text)
            entities = result.get("entities", []) if isinstance(result, dict) else []
            relations = result.get("relations", []) if isinstance(result, dict) else []
            logger.info(f"Extracted {len(entities)} entitie(s) and {len(relations)} relation(s)")

            entity_ids: dict[str, str] = {}
            for entity in entities:
                created = backend_client.upsert_entity(collection_id, str(entity["name"]), str(entity["type"]))
                entity_ids[str(entity["name"])] = created["id"]

            for relation in relations:
                from_id = entity_ids.get(str(relation.get("from")))
                to_id = entity_ids.get(str(relation.get("to")))
                if from_id is None or to_id is None:
                    logger.warning(f"Skipping relation with unresolved entity: {relation!r}")
                    continue
                backend_client.create_relation(collection_id, from_id, to_id, str(relation["type"]))
        except Exception as error:
            _fail(document_id, f"extract entities for pages {start_page}-{end_page}", error)
            raise


@celery_app.task(name="app.tasks.update_collection_description", bind=True)
def update_collection_description(self, document_id: str, collection_id: str) -> None:
    """Keeps the collection's description in sync with what's actually in
    it: synthesizes one from every document summary the first time there is
    no description yet, or asks the model whether this document's new
    summary should change the existing one (and if so, how) after that.
    Always a full replace, never appended - same for update_collection_tags.
    Dispatches generate_collection_qa when the description actually changes."""
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "summary")
            if model is None:
                logger.warning(f"No model available to maintain the description for {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("summary", "")
            metadata = backend_client.get_collection_metadata(collection_id)
            if not metadata["description"]:
                if not metadata["document_summaries"]:
                    return
                combined = "\n\n---\n\n".join(metadata["document_summaries"])
                prompt = (
                    f"{instructions}\nWrite a short, factual description (2-4 sentences) of a document collection, "
                    "based on the summaries of the documents it contains. Respond with only the description."
                ).strip()
                new_description = _chat(model, prompt, combined).strip()
            else:
                document = backend_client.get_document(document_id)
                new_summary = document.get("summary") or ""
                if not new_summary:
                    return
                prompt = (
                    f"{instructions}\nYou maintain a short description for a document collection. You are given "
                    "the current description and the summary of a document newly added to the collection. Decide "
                    "whether the description still accurately represents the collection. If it does, respond "
                    "with it unchanged. If not, respond with an updated description (2-4 sentences). Respond with "
                    "only the description text, nothing else."
                ).strip()
                user_content = (
                    f"Current description:\n{metadata['description']}\n\nNew document summary:\n{new_summary}"
                )
                new_description = _chat(model, prompt, user_content).strip()

            if new_description and new_description != metadata["description"]:
                backend_client.update_collection_description(collection_id, new_description)
                logger.info(f"Description updated for collection {collection_id} ({len(new_description)} chars)")

                # Global embedding model (admin-configured, or the hub's
                # default), not the collection's own embedding_model - every
                # collection must land in the same embedding space for a
                # query to be matched against them by similarity.
                try:
                    embedding_model = backend_client.get_default_embedding_model()
                    if embedding_model is not None:
                        embedding = backend_client.embed(embedding_model, new_description)
                        backend_client.update_collection_description_embedding(
                            collection_id, embedding_model, embedding
                        )
                except Exception:
                    logger.exception(f"Failed to embed the new description for collection {collection_id}")

                _spawn(
                    generate_collection_qa,
                    [document_id, collection_id, new_description],
                    "app.tasks.generate_collection_qa",
                    document_id,
                    self.request.id,
                )
            else:
                logger.info(f"Description for collection {collection_id} left unchanged")
        except Exception as error:
            _fail(document_id, "update the collection description", error)
            raise


@celery_app.task(name="app.tasks.update_collection_tags", bind=True)
def update_collection_tags(self, document_id: str, collection_id: str) -> None:
    """Mirrors update_collection_description for the collection's tags:
    synthesizes them from every document summary the first time there are
    none, or asks whether the current tags still fit given this document's
    new summary after that."""
    with capture_task_logs(self.request.id):
        try:
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "tagging")
            if model is None:
                logger.warning(f"No model available to maintain tags for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("tagging", "")
            metadata = backend_client.get_collection_metadata(collection_id)
            if not metadata["tags"]:
                if not metadata["document_summaries"]:
                    return
                content = "\n\n---\n\n".join(metadata["document_summaries"])
                prompt = (
                    f"{instructions}\nSuggest up to 8 short, lowercase tags describing this document collection, "
                    "based on the summaries of the documents it contains. Respond only with a JSON array of tag "
                    "strings."
                ).strip()
            else:
                document = backend_client.get_document(document_id)
                new_summary = document.get("summary") or ""
                if not new_summary:
                    return
                content = f"Current tags: {metadata['tags']}\n\nNew document summary:\n{new_summary}"
                prompt = (
                    f"{instructions}\nYou maintain tags for a document collection. Given the current tags and a "
                    "newly added document's summary, decide whether the tags still fit. Respond only with a JSON "
                    "array of up to 8 short, lowercase tag strings - the full updated list (or the same list, "
                    "unchanged)."
                ).strip()

            tags = _chat_json(model, prompt, content)
            if not isinstance(tags, list):
                raise ValueError(f"Expected a JSON array of tags, got: {tags!r}")
            tags = [str(tag) for tag in tags]

            if set(tags) != set(metadata["tags"]):
                backend_client.update_collection_tags(collection_id, tags)
                logger.info(f"Tags updated for collection {collection_id}: {len(tags)} tag(s)")
            else:
                logger.info(f"Tags for collection {collection_id} left unchanged")
        except Exception as error:
            _fail(document_id, "update the collection tags", error)
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
            settings = backend_client.get_collection_settings(collection_id)
            model = _model_for(settings, "qa")
            if model is None:
                logger.warning(f"No QA model available for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("qa", "")
            count = _windows(settings)["collection_qa_count"]
            prompt = (
                f"{instructions}\nGenerate exactly {count} question/answer pairs about this document collection, "
                "grounded strictly in the given description. Respond only with a JSON array of "
                '{"question": ..., "answer": ...} objects.'
            ).strip()
            pairs = _chat_json(model, prompt, description)
            if not isinstance(pairs, list):
                raise ValueError(f"Expected a JSON array of QA pairs, got: {pairs!r}")

            for pair in pairs:
                backend_client.create_qa_pair(collection_id, None, str(pair["question"]), str(pair["answer"]))
            logger.info(f"Generated {len(pairs)} collection-level QA pair(s) for collection {collection_id}")
        except Exception as error:
            _fail(document_id, "generate collection-level QA pairs", error)
            raise
