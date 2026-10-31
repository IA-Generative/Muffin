"""Tâches de maintenance de la collection (description et tags).

- ``update_collection_description`` : synthétise ou met à jour la description
  de la collection à partir des résumés de documents. Dispatche
  ``generate_collection_qa`` quand la description change.
- ``update_collection_tags`` : maintient les tags de la collection de la
  même façon.
- ``rollup_collection_description`` : recalcule la description d'une
  collection parente à partir de ses documents propres et des descriptions de
  ses sous-collections (#218). Programmée par le backend, jamais par ce worker.
"""

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared
from app.tasks.qa import generate_collection_qa  # noqa: E402,F401


def _publish_description(collection_id: str, description: str) -> None:
    """Stores a changed description - which is also what makes the backend schedule the parent's
    rollup, see rollup_collection_description - then indexes its embedding."""
    _shared.backend_client.update_collection_description(collection_id, description)
    logger.info(f"Description updated for collection {collection_id} ({len(description)} chars)")
    _index_description(collection_id, description)


def _index_description(collection_id: str, description: str) -> None:
    # Global embedding model (admin-configured, or the hub's
    # default), not the collection's own embedding_model - every
    # collection must land in the same embedding space for a
    # query to be matched against them by similarity.
    try:
        embedding_model = _shared.backend_client.get_default_embedding_model()
        if embedding_model is not None:
            embedding = _shared.backend_client.embed(embedding_model, description)
            _shared.backend_client.update_collection_description_embedding(collection_id, embedding)
    except Exception:
        logger.exception(f"Failed to embed the new description for collection {collection_id}")


def _maintain_description(document_id: str, collection_id: str) -> str | None:
    """Brings the description of the collection up to date with the summary of this document, see
    update_collection_description. Returns the new description, None when it stays as it was (or cannot be made)."""
    settings = _shared.backend_client.get_collection_settings(collection_id)
    model = _shared._model_for(settings, "summary")
    if model is None:
        logger.warning(f"No model available to maintain the description for {collection_id}, skipping")
        return None

    instructions = settings["instructions"].get("summary", "")
    metadata = _shared.backend_client.get_collection_metadata(collection_id)
    if not metadata["description"]:
        if not metadata["document_summaries"]:
            return None
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
            return None
        prompt = (
            f"{instructions}\nYou maintain a short description for a document collection. You are given "
            "the current description and the summary of a document newly added to the collection. Decide "
            "whether the description still accurately represents the collection. If it does, respond "
            "with it unchanged. If not, respond with an updated description (2-4 sentences). Respond with "
            "only the description text, nothing else."
        ).strip()
        user_content = f"Current description:\n{metadata['description']}\n\nNew document summary:\n{new_summary}"
        new_description = _shared._chat(model, prompt, user_content).strip()

    if new_description and new_description != metadata["description"]:
        _publish_description(collection_id, new_description)
        return new_description
    logger.info(f"Description for collection {collection_id} left unchanged")
    return None


@celery_app.task(name="app.tasks.update_collection_description", bind=True)
def update_collection_description(self, document_id: str, collection_id: str) -> None:
    """Keeps the collection's description in sync with what's actually in
    it: synthesizes one from every document summary the first time there is
    no description yet, or asks the model whether this document's new
    summary should change the existing one (and if so, how) after that.
    Always a full replace, never appended - same for update_collection_tags.
    Dispatches generate_collection_qa when the description actually changes."""
    try:
        new_description = _maintain_description(document_id, collection_id)
        if new_description is not None:
            _shared._spawn(
                generate_collection_qa,
                [document_id, collection_id, new_description],
                "app.tasks.generate_collection_qa",
                document_id,
                self.request.id,
            )
    except Exception as error:
        _shared._fail(document_id, "update the collection description", error)
        raise


@celery_app.task(name="app.tasks.update_collection_tags", bind=True)
def update_collection_tags(self, document_id: str, collection_id: str) -> None:
    """Mirrors update_collection_description for the collection's tags:
    synthesizes them from every document summary the first time there are
    none, or asks whether the current tags still fit given this document's
    new summary after that."""
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


@celery_app.task(name="app.tasks.rollup_collection_description", bind=True)
def rollup_collection_description(self, collection_id: str) -> None:
    """Recomputes a parent collection's description from its own document summaries and its
    direct sub-collections' descriptions (#218), so the research agent can tell from the parent
    alone whether its subtree is worth descending into.

    Scheduled by the backend, delayed so that every change below within that window is read
    here at once. A changed description is reported like any other, which schedules the next
    level up; an unchanged one stops the propagation. Unlike update_collection_description, no
    collection QA pairs are generated: there is no triggering document to attach that task to.
    """
    settings = _shared.backend_client.get_collection_settings(collection_id)
    model = _shared._model_for(settings, "summary")
    if model is None:
        logger.warning(f"No model available to roll up the description of {collection_id}, skipping")
        return

    metadata = _shared.backend_client.get_collection_metadata(collection_id)
    sub_collections = metadata.get("sub_collections") or []
    if not sub_collections:
        # Nothing to roll up: its own documents already keep it current, document by document.
        logger.info(f"Collection {collection_id} has no described sub-collection, nothing to roll up")
        return

    content = "Sub-collections:\n" + "\n".join(
        f"- {sub_collection['name']}: {sub_collection['description']}" for sub_collection in sub_collections
    )
    if metadata["document_summaries"]:
        content += "\n\nDocuments directly in this collection:\n" + "\n\n---\n\n".join(metadata["document_summaries"])

    instructions = settings["instructions"].get("summary", "")
    if not metadata["description"]:
        prompt = (
            f"{instructions}\nWrite a short, factual description (2-4 sentences) of a document collection "
            "that is organised into sub-collections, based on the sub-collections' descriptions and the "
            "summaries of the documents directly in it. Cover what the whole collection contains, so a "
            "reader can tell whether it is worth looking into. Respond with only the description."
        ).strip()
        user_content = content
    else:
        prompt = (
            f"{instructions}\nYou maintain a short description for a document collection that is organised "
            "into sub-collections. You are given its current description, its sub-collections' descriptions "
            "and the summaries of the documents directly in it. Decide whether the description still "
            "accurately represents the whole collection. If it does, respond with it unchanged. If not, "
            "respond with an updated description (2-4 sentences). Respond with only the description text, "
            "nothing else."
        ).strip()
        user_content = f"Current description:\n{metadata['description']}\n\n{content}"

    new_description = _shared._chat(model, prompt, user_content).strip()
    if new_description and new_description != metadata["description"]:
        _publish_description(collection_id, new_description)
    else:
        logger.info(f"Rolled-up description for collection {collection_id} left unchanged")
