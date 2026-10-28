from typing import Any

import httpx

from app.config import settings
from app.usage_context import current_usage


class Embedding(list):
    """A vector that remembers the model it was made with. Sent along with it wherever it is stored,
    so the backend can tell a vector made with another model than its index's - one computed just
    before the index was rebuilt with a new model (#12) - and redo it."""

    def __init__(self, values: list[float], model: str) -> None:
        super().__init__(values)
        self.model = model


def _model_of(embedding: list[float] | None) -> str | None:
    return getattr(embedding, "model", None)


class BackendClient:
    """Talks to the backend's /api/internal/* routes, authenticated with the
    shared WORKER_API_KEY instead of a Keycloak session."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.BACKEND_API_URL,
            headers={"X-API-Key": settings.WORKER_API_KEY},
            timeout=60.0,
        )

    # --- ZIP import (#223) ---

    def begin_collection_import(self, import_id: str) -> dict[str, Any]:
        response = self._client.post(f"/api/internal/collection-imports/{import_id}/begin")
        response.raise_for_status()
        return response.json()

    def create_imported_collection(self, import_id: str, parent_id: str, name: str) -> str:
        response = self._client.post(
            f"/api/internal/collection-imports/{import_id}/collections", json={"parent_id": parent_id, "name": name}
        )
        response.raise_for_status()
        return response.json()["id"]

    def is_imported_duplicate(self, import_id: str, collection_id: str, content_hash: str) -> bool:
        """Whether the collection already holds a file of this hash (#300) - asked before a file of the
        archive is stored, so that a duplicate is neither stored nor processed."""
        response = self._client.post(
            f"/api/internal/collection-imports/{import_id}/documents/check",
            json={"collection_id": collection_id, "content_hash": content_hash},
        )
        response.raise_for_status()
        return response.json()["duplicate"]

    def add_imported_document(
        self, import_id: str, collection_id: str, name: str, storage_key: str, content_hash: str
    ) -> str | None:
        """The id of the document, or None when the collection holds this file already (#334): another batch
        of the import registered it meanwhile, and the backend dropped the stored copy."""
        response = self._client.post(
            f"/api/internal/collection-imports/{import_id}/documents",
            json={
                "collection_id": collection_id,
                "name": name,
                "storage_key": storage_key,
                "content_hash": content_hash,
            },
        )
        response.raise_for_status()
        return response.json()["id"]

    def begin_import_batches(self, import_id: str, expected: list[str], plan: dict[str, Any]) -> None:
        """The batches of files a big archive is read in (#334), with the planner's part of the summary."""
        response = self._client.post(
            f"/api/internal/collection-imports/{import_id}/batches/begin", json={"expected": expected, "plan": plan}
        )
        response.raise_for_status()

    def import_batch_done(self, import_id: str, key: str, result: dict[str, Any]) -> dict[str, Any]:
        """A batch reported: where the import is - `status`, `done` of `expected` - and, for the one batch
        that `completed_now` it, the `summary` of the whole."""
        response = self._client.post(f"/api/internal/collection-imports/{import_id}/batches/{key}/done", json=result)
        response.raise_for_status()
        return response.json()

    def finish_collection_import(
        self, import_id: str, status: str, summary: dict[str, Any], error: str | None = None
    ) -> None:
        response = self._client.put(
            f"/api/internal/collection-imports/{import_id}/result",
            json={"status": status, "summary": summary, "error": error},
        )
        response.raise_for_status()

    def get_document(self, document_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/documents/{document_id}")
        response.raise_for_status()
        return response.json()

    def update_status(
        self,
        document_id: str,
        status: str,
        progress: int | None = None,
        summary: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"status": status}
        if progress is not None:
            body["progress"] = progress
        if summary is not None:
            body["summary"] = summary
        response = self._client.patch(f"/api/internal/documents/{document_id}/status", json=body)
        response.raise_for_status()

    def add_page(
        self,
        document_id: str,
        page_number: int,
        content: str,
        screenshot: str | None = None,
        text_boxes: list[dict[str, Any]] | None = None,
        regions: list[dict[str, Any]] | None = None,
    ) -> None:
        """`text_boxes`: the page's lines and words with their boxes (#350). `regions`: the regions of its layout, in
        reading order (#409). Not given, what the page has is kept; given, even empty, it replaces it."""
        body: dict[str, Any] = {"page_number": page_number, "content": content, "screenshot": screenshot}
        if text_boxes is not None:
            body["text_boxes"] = text_boxes
        if regions is not None:
            body["regions"] = regions
        response = self._client.post(f"/api/internal/documents/{document_id}/pages", json=body)
        response.raise_for_status()

    def get_pages(self, document_id: str) -> list[dict[str, Any]]:
        response = self._client.get(f"/api/internal/documents/{document_id}/pages")
        response.raise_for_status()
        return response.json()

    def add_chunk(
        self,
        document_id: str,
        index: int,
        text: str,
        token_count: int,
        extras: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> None:
        response = self._client.post(
            f"/api/internal/documents/{document_id}/chunks",
            json={
                "index": index,
                "text": text,
                "token_count": token_count,
                "extras": extras,
                "embedding": embedding,
                "embedding_model": _model_of(embedding),
            },
        )
        response.raise_for_status()

    def begin_stage(
        self,
        document_id: str,
        stage: str,
        fingerprint: str,
        expected: list[str],
        content_hash: str | None = None,
    ) -> bool:
        """A stage is about to run (#300): True if another document of the same file already completed
        it under this fingerprint and the backend copied its results here - nothing is left to compute."""
        body: dict[str, Any] = {"fingerprint": fingerprint, "expected": expected}
        if content_hash:
            body["content_hash"] = content_hash
        response = self._client.post(f"/api/internal/documents/{document_id}/stages/{stage}/begin", json=body)
        response.raise_for_status()
        return response.json()["reused"]

    def extraction_done(self, document_id: str) -> None:
        """The document's extraction ended, the chunking takes over (#335): when it is a document of a ZIP
        import, its place in the import's window goes to the next one. A no-op for any other document."""
        response = self._client.post(f"/api/internal/documents/{document_id}/extraction-done")
        response.raise_for_status()

    def release_import_queue(self) -> int:
        """The sweep of the imports' windows (#335): the backend releases what each window allows."""
        response = self._client.post("/api/internal/collection-imports/release")
        response.raise_for_status()
        return response.json()["released"]

    def stage_done(self, document_id: str, stage: str, key: str = "_") -> dict[str, Any]:
        """A piece of a stage is done. Says where the stage is: `done` pieces of the `expected` ones, whether it
        is `complete`, and whether this very piece `completed_now` it - the one to carry on after the stage."""
        response = self._client.post(f"/api/internal/documents/{document_id}/stages/{stage}/done", json={"key": key})
        response.raise_for_status()
        return response.json()

    def prune_pages(self, document_id: str, keep: int) -> None:
        """After writing the pages: drops those after the first `keep` that an earlier, longer run left."""
        response = self._client.post(f"/api/internal/documents/{document_id}/pages/prune", json={"keep": keep})
        response.raise_for_status()

    def prune_chunks(self, document_id: str, keep: int) -> None:
        """Same for the chunks, with their vectors."""
        response = self._client.post(f"/api/internal/documents/{document_id}/chunks/prune", json={"keep": keep})
        response.raise_for_status()

    def set_document_summary(
        self,
        document_id: str,
        summary: str,
        embedding: list[float] | None = None,
        pages: list[tuple[int, int]] | None = None,
    ) -> None:
        """`pages`: the stretches of pages the summary was made from (#372) - None when it read the whole document."""
        response = self._client.patch(
            f"/api/internal/documents/{document_id}/summary",
            json={
                "summary": summary,
                "embedding": embedding,
                "embedding_model": _model_of(embedding),
                "pages": [list(stretch) for stretch in pages] if pages else None,
            },
        )
        response.raise_for_status()

    def prune_windows(self, document_id: str, qa: list[str] | None = None, entities: list[str] | None = None) -> None:
        """Keeps, of what was derived from the document's windows of pages (#372), only the windows given - by key,
        "window:3-4" for the QA pairs and "pages:3-6" for the entities. A step left out is left alone."""
        response = self._client.post(
            f"/api/internal/documents/{document_id}/windows/prune", json={"qa": qa, "entities": entities}
        )
        response.raise_for_status()

    def suggest_filing(self, document_id: str) -> None:
        response = self._client.post(f"/api/internal/documents/{document_id}/suggest-filing")
        response.raise_for_status()

    def set_content_hash(self, document_id: str, content_hash: str, storage_key: str | None = None) -> None:
        response = self._client.put(
            f"/api/internal/documents/{document_id}/content-hash",
            json={"content_hash": content_hash, "storage_key": storage_key},
        )
        response.raise_for_status()

    # --- Blue/green index rebuild (#12) ---

    def get_rebuild_plan(self, rebuild_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/index-rebuilds/{rebuild_id}/plan")
        response.raise_for_status()
        return response.json()

    def submit_rebuild_vectors(self, rebuild_id: str, model: str, points: list[dict[str, Any]]) -> int:
        response = self._client.post(
            f"/api/internal/index-rebuilds/{rebuild_id}/vectors", json={"model": model, "points": points}
        )
        response.raise_for_status()
        return response.json()["stored"]

    def swap_rebuild(self, rebuild_id: str) -> bool:
        """Whether the new index is now the active one - False while the backend still sees points missing."""
        response = self._client.post(f"/api/internal/index-rebuilds/{rebuild_id}/swap")
        response.raise_for_status()
        return response.json()["swapped"]

    def fail_rebuild(self, rebuild_id: str, error: str) -> None:
        response = self._client.post(f"/api/internal/index-rebuilds/{rebuild_id}/fail", json={"error": error})
        response.raise_for_status()

    def claim_url_refresh(self) -> list[str]:
        """The URL documents due for a refresh - each claimed once, even with several scans at once."""
        response = self._client.post("/api/internal/url-refresh/claim")
        response.raise_for_status()
        return [str(document_id) for document_id in response.json()["document_ids"]]

    def report_url_fetch(self, document_id: str, content_hash: str) -> bool:
        """Whether the page changed - the backend then reprocesses the document."""
        response = self._client.post(
            f"/api/internal/documents/{document_id}/url-refresh", json={"content_hash": content_hash}
        )
        response.raise_for_status()
        return bool(response.json()["changed"])

    def set_document_error(self, document_id: str, error: str) -> None:
        response = self._client.patch(f"/api/internal/documents/{document_id}/error", json={"error": error})
        response.raise_for_status()

    def set_tabular_profile(self, document_id: str, profile: dict[str, Any]) -> None:
        """Persiste le profil tabulaire (stats DuckDB) d'un document via
        l'endpoint interne dédié. Le profil est un JSONB côté backend."""
        response = self._client.post(f"/api/internal/documents/{document_id}/tabular-profile", json=profile)
        response.raise_for_status()

    def replace_document_tags(self, document_id: str, tags: list[str]) -> None:
        response = self._client.put(f"/api/internal/documents/{document_id}/tags", json={"tags": tags})
        response.raise_for_status()

    def get_collection_settings(self, collection_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/collections/{collection_id}/settings")
        response.raise_for_status()
        return response.json()

    def replace_generated_qa(
        self,
        collection_id: str,
        document_id: str | None,
        key: str,
        pairs: list[dict[str, Any]],
    ) -> None:
        """Records the pairs one run generated (a window "window:1-2", "tabular", "collection:<hash>"), in
        place of what the previous run of the same key recorded: a task run twice leaves the same pairs.
        Each is {"question", "answer", "embedding"?, "source_page"?, "source_excerpt"?, "source_start"?,
        "source_end"?} - the last two where the passage is in its page (#351)."""
        response = self._client.put(
            f"/api/internal/collections/{collection_id}/qa-pairs/generated",
            json={
                "document_id": document_id,
                "key": key,
                "pairs": [
                    {
                        "question": pair["question"],
                        "answer": pair["answer"],
                        "embedding": pair.get("embedding"),
                        "embedding_model": _model_of(pair.get("embedding")),
                        "source_page": pair.get("source_page"),
                        "source_excerpt": pair.get("source_excerpt"),
                        "source_start": pair.get("source_start"),
                        "source_end": pair.get("source_end"),
                    }
                    for pair in pairs
                ],
            },
        )
        response.raise_for_status()

    def replace_entity_window(
        self,
        document_id: str,
        window_key: str,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> None:
        """Records what was extracted from one window of pages - entities {"name", "type", "mentions"?,
        "occurrences"?: [{"page", "start", "end"}]} and relations {"from_name", "to_name", "type",
        "source_page"?, "source_excerpt"?, "source_start"?, "source_end"?} - in place of the previous
        extraction of it. The occurrences are where the entity is in the text of the window, the source of a
        relation the sentence behind it (#352)."""
        response = self._client.put(
            f"/api/internal/documents/{document_id}/entity-windows/{window_key}",
            json={"entities": entities, "relations": relations},
        )
        response.raise_for_status()

    def create_task(
        self,
        celery_task_id: str,
        task_name: str,
        document_id: str,
        parent_celery_task_id: str | None = None,
    ) -> None:
        response = self._client.post(
            "/api/internal/tasks",
            json={
                "celery_task_id": celery_task_id,
                "task_name": task_name,
                "document_id": document_id,
                "parent_celery_task_id": parent_celery_task_id,
            },
        )
        response.raise_for_status()

    def add_task_logs(self, lines: list[dict]) -> None:
        """A short timeout: the lines are sent again with the next batch, a task never waits on them."""
        response = self._client.post("/api/internal/task-logs", json={"entries": lines}, timeout=5.0)
        response.raise_for_status()

    def purge_task_logs(self) -> int:
        response = self._client.delete("/api/internal/task-logs")
        response.raise_for_status()
        return response.json()["deleted"]

    def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        response = self._client.post(
            "/api/internal/llm/chat",
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "usage": current_usage()},
        )
        response.raise_for_status()
        return response.json()["content"]

    def get_default_chat_model(self) -> str | None:
        response = self._client.get("/api/internal/llm/default-chat-model")
        response.raise_for_status()
        return response.json()["model"]

    def get_default_embedding_model(self) -> str | None:
        response = self._client.get("/api/internal/llm/default-embedding-model")
        response.raise_for_status()
        return response.json()["model"]

    def get_collection_metadata(self, collection_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/collections/{collection_id}/metadata")
        response.raise_for_status()
        return response.json()

    def update_collection_description(self, collection_id: str, description: str) -> None:
        response = self._client.patch(
            f"/api/internal/collections/{collection_id}/description",
            json={"description": description},
        )
        response.raise_for_status()

    def update_collection_tags(self, collection_id: str, tags: list[str]) -> None:
        response = self._client.put(f"/api/internal/collections/{collection_id}/tags", json={"tags": tags})
        response.raise_for_status()

    def embed(self, model: str, text: str) -> list[float]:
        response = self._client.post(
            "/api/internal/llm/embed", json={"model": model, "input": text, "usage": current_usage()}
        )
        response.raise_for_status()
        return Embedding(response.json()["embedding"], model)

    def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
        """One call for many texts - what an index rebuild (#12) uses to redo thousands of vectors."""
        response = self._client.post(
            "/api/internal/llm/embed-batch", json={"model": model, "inputs": texts, "usage": current_usage()}
        )
        response.raise_for_status()
        return response.json()["embeddings"]

    def update_collection_description_embedding(self, collection_id: str, embedding: list[float]) -> None:
        """Not persisted in Postgres - indexed straight into Qdrant (§124), which is now
        the only place a collection's description embedding lives."""
        response = self._client.patch(
            f"/api/internal/collections/{collection_id}/description-embedding",
            json={"embedding": embedding},
        )
        response.raise_for_status()

    def add_execution_metric(self, metric: dict) -> None:
        """A short timeout: it is sent from a thread of its own and dropped if it fails, a task never waits on it."""
        response = self._client.post("/api/internal/execution-metrics", json=metric, timeout=5.0)
        response.raise_for_status()


backend_client = BackendClient()
