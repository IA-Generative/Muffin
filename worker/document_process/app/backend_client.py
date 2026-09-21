from typing import Any

import httpx

from app.config import settings


class BackendClient:
    """Talks to the backend's /api/internal/* routes, authenticated with the
    shared WORKER_API_KEY instead of a Keycloak session."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.BACKEND_API_URL,
            headers={"X-API-Key": settings.WORKER_API_KEY},
            timeout=60.0,
        )

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
    ) -> None:
        response = self._client.post(
            f"/api/internal/documents/{document_id}/pages",
            json={
                "page_number": page_number,
                "content": content,
                "screenshot": screenshot,
            },
        )
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
            },
        )
        response.raise_for_status()

    def set_document_summary(self, document_id: str, summary: str, embedding: list[float] | None = None) -> None:
        response = self._client.patch(
            f"/api/internal/documents/{document_id}/summary",
            json={"summary": summary, "embedding": embedding},
        )
        response.raise_for_status()

    def suggest_filing(self, document_id: str) -> None:
        response = self._client.post(f"/api/internal/documents/{document_id}/suggest-filing")
        response.raise_for_status()

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

    def create_qa_pair(
        self,
        collection_id: str,
        document_id: str | None,
        question: str,
        answer: str,
        embedding: list[float] | None = None,
    ) -> None:
        response = self._client.post(
            f"/api/internal/collections/{collection_id}/qa-pairs",
            json={
                "document_id": document_id,
                "question": question,
                "answer": answer,
                "embedding": embedding,
            },
        )
        response.raise_for_status()

    def upsert_entity(
        self,
        collection_id: str,
        document_id: str,
        name: str,
        type_: str,
        mentions_delta: int = 1,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/api/internal/collections/{collection_id}/entities",
            json={
                "document_id": document_id,
                "name": name,
                "type": type_,
                "mentions_delta": mentions_delta,
            },
        )
        response.raise_for_status()
        return response.json()

    def create_relation(
        self,
        collection_id: str,
        document_id: str,
        from_entity_id: str,
        to_entity_id: str,
        type_: str,
    ) -> None:
        response = self._client.post(
            f"/api/internal/collections/{collection_id}/relations",
            json={
                "document_id": document_id,
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "type": type_,
            },
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

    def set_task_logs(self, celery_task_id: str, logs: str) -> None:
        response = self._client.patch(f"/api/internal/tasks/{celery_task_id}/logs", json={"logs": logs})
        response.raise_for_status()

    def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        response = self._client.post(
            "/api/internal/llm/chat",
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
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
        response = self._client.post("/api/internal/llm/embed", json={"model": model, "input": text})
        response.raise_for_status()
        return response.json()["embedding"]

    def update_collection_description_embedding(self, collection_id: str, embedding: list[float]) -> None:
        """Not persisted in Postgres - indexed straight into Meilisearch (§124), which is now
        the only place a collection's description embedding lives."""
        response = self._client.patch(
            f"/api/internal/collections/{collection_id}/description-embedding",
            json={"embedding": embedding},
        )
        response.raise_for_status()


backend_client = BackendClient()
