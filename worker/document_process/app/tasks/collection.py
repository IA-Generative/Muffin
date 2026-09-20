"""Tâches de maintenance de la collection (description et tags).

- ``update_collection_description`` : synthétise ou met à jour la description
  de la collection à partir des résumés de documents. Dispatche
  ``generate_collection_qa`` quand la description change.
- ``update_collection_tags`` : maintient les tags de la collection de la
  même façon.
"""

from loguru import logger

from app.celery_app import celery_app
from app.task_logging import capture_task_logs
from app.tasks import _shared
from app.tasks.qa import generate_collection_qa  # noqa: E402,F401


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
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "summary")
            if model is None:
                logger.warning(f"No model available to maintain the description for {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("summary", "")
            metadata = _shared.backend_client.get_collection_metadata(collection_id)
            if not metadata["description"]:
                if not metadata["document_summaries"]:
                    return
                combined = "\n\n---\n\n".join(metadata["document_summaries"])
                prompt = (
                    f"{instructions}\nWrite a short, factual description (2-4 sentences) of a document collection, "
                    "based on the summaries of the documents it contains. Respond with only the description."
                ).strip()
                new_description = _shared._chat(model, prompt, combined).strip()
            else:
                document = _shared.backend_client.get_document(document_id)
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
                new_description = _shared._chat(model, prompt, user_content).strip()

            if new_description and new_description != metadata["description"]:
                _shared.backend_client.update_collection_description(collection_id, new_description)
                logger.info(f"Description updated for collection {collection_id} ({len(new_description)} chars)")

                # Global embedding model (admin-configured, or the hub's
                # default), not the collection's own embedding_model - every
                # collection must land in the same embedding space for a
                # query to be matched against them by similarity.
                try:
                    embedding_model = _shared.backend_client.get_default_embedding_model()
                    if embedding_model is not None:
                        embedding = _shared.backend_client.embed(embedding_model, new_description)
                        _shared.backend_client.update_collection_description_embedding(
                            collection_id, embedding_model, embedding
                        )
                except Exception:
                    logger.exception(f"Failed to embed the new description for collection {collection_id}")

                _shared._spawn(
                    generate_collection_qa,
                    [document_id, collection_id, new_description],
                    "app.tasks.generate_collection_qa",
                    document_id,
                    self.request.id,
                )
            else:
                logger.info(f"Description for collection {collection_id} left unchanged")
        except Exception as error:
            _shared._fail(document_id, "update the collection description", error)
            raise


@celery_app.task(name="app.tasks.update_collection_tags", bind=True)
def update_collection_tags(self, document_id: str, collection_id: str) -> None:
    """Mirrors update_collection_description for the collection's tags:
    synthesizes them from every document summary the first time there are
    none, or asks whether the current tags still fit given this document's
    new summary after that."""
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "tagging")
            if model is None:
                logger.warning(f"No model available to maintain tags for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("tagging", "")
            metadata = _shared.backend_client.get_collection_metadata(collection_id)
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
                document = _shared.backend_client.get_document(document_id)
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

            tags = _shared._chat_json(model, prompt, content)
            if not isinstance(tags, list):
                raise ValueError(f"Expected a JSON array of tags, got: {tags!r}")
            tags = [str(tag) for tag in tags]

            if set(tags) != set(metadata["tags"]):
                _shared.backend_client.update_collection_tags(collection_id, tags)
                logger.info(f"Tags updated for collection {collection_id}: {len(tags)} tag(s)")
            else:
                logger.info(f"Tags for collection {collection_id} left unchanged")
        except Exception as error:
            _shared._fail(document_id, "update the collection tags", error)
            raise
