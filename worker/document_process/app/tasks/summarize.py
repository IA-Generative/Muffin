"""Tâches de résumé et de tagging de document.

- ``summarize_document`` : map-reduce (un résumé partiel par batch de pages,
  puis une passe de combinaison). Dispatche ``tag_document`` et les mises à
  jour de collection après succès.
- ``tag_document`` : lit le résumé et demande une liste courte de tags.
"""

from loguru import logger

from app.celery_app import celery_app
from app.task_logging import capture_task_logs
from app.tasks import _shared
from app.tasks.collection import (  # noqa: E402,F401
    update_collection_description,
    update_collection_tags,
)


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
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "summary")
            if model is None:
                logger.warning(f"No summary model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("summary", "")
            pages = _shared._get_pages(document_id)
            pages_per_map = _shared._windows(settings)["summary_pages_per_map"]
            logger.info(f"Summarizing document {document_id}: {len(pages)} page(s), {pages_per_map} page(s) per map")

            partials = [
                _shared._chat(
                    model,
                    f"{instructions}\nSummarize the following excerpt concisely.".strip(),
                    "\n\n".join(page.content for page in batch),
                )
                for batch in _shared._batches(pages, pages_per_map)
            ]

            if len(partials) == 1:
                summary = partials[0]
            else:
                summary = _shared._chat(
                    model,
                    f"{instructions}\nCombine the following partial summaries into one coherent summary.".strip(),
                    "\n\n---\n\n".join(partials),
                )

            # Best-effort, same fail-soft reasoning as a chunk's own embedding: a summary with no
            # embedding still exists and still works for everything except the research agent's
            # tier-2 (summary) retrieval, which just never surfaces it.
            summary_embedding = None
            try:
                summary_embedding = _shared.backend_client.embed(settings["embedding_model"], summary)
            except Exception:
                logger.exception(f"Failed to embed summary for document {document_id}")
            _shared.backend_client.set_document_summary(document_id, summary, summary_embedding)
            logger.info(f"Summary for document {document_id} saved ({len(summary)} chars)")

            parent_id = self.request.id
            _shared._spawn(
                tag_document,
                [document_id, collection_id],
                "app.tasks.tag_document",
                document_id,
                parent_id,
            )
            _shared._spawn(
                update_collection_description,
                [document_id, collection_id],
                "app.tasks.update_collection_description",
                document_id,
                parent_id,
            )
            _shared._spawn(
                update_collection_tags,
                [document_id, collection_id],
                "app.tasks.update_collection_tags",
                document_id,
                parent_id,
            )
        except Exception as error:
            _shared._fail(document_id, "summarize", error)
            raise


@celery_app.task(name="app.tasks.tag_document", bind=True)
def tag_document(self, document_id: str, collection_id: str) -> None:
    """Reads the summary summarize_document just produced (falling back to
    the first page if there isn't one yet) and asks for a short list of
    tags."""
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "tagging")
            if model is None:
                logger.warning(f"No tagging model configured for collection {collection_id}, skipping")
                return

            document = _shared.backend_client.get_document(document_id)
            instructions = settings["instructions"].get("tagging", "")
            content = document.get("summary") or "\n\n".join(
                page.content for page in _shared._get_pages(document_id)[:1]
            )

            prompt = f"{instructions}\nRespond only with a JSON array of short, lowercase tag strings (no more than 8)."
            tags = _shared._chat_json(model, prompt.strip(), content)
            if not isinstance(tags, list):
                raise ValueError(f"Expected a JSON array of tags, got: {tags!r}")

            _shared.backend_client.replace_document_tags(document_id, [str(tag) for tag in tags])
            logger.info(f"Saved {len(tags)} tag(s) for document {document_id}")
        except Exception as error:
            _shared._fail(document_id, "tag", error)
            raise
