from typing import Any

import httpx

from app.config import settings


class BackendClient:
    """Talks to the backend's /api/internal/* routes, authenticated with the
    shared WORKER_API_KEY instead of a Keycloak session - same pattern as
    worker/document_process/app/backend_client.py."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.BACKEND_API_URL,
            headers={"X-API-Key": settings.WORKER_API_KEY},
            timeout=60.0,
        )

    def get_collection_settings(self, collection_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/collections/{collection_id}/settings")
        response.raise_for_status()
        return response.json()

    def list_qa_pairs(self, collection_id: str) -> list[dict[str, Any]]:
        """Every QA pair of the collection, validated or not - each carries its own `validated`
        flag, which the worker groups its aggregates by (see #11's follow-up: evaluate both, not
        just validated ones)."""
        response = self._client.get(f"/api/internal/collections/{collection_id}/qa-pairs")
        response.raise_for_status()
        return response.json()

    def get_document_chunk_count(self, document_id: str) -> int:
        response = self._client.get(f"/api/internal/documents/{document_id}/chunk-count")
        response.raise_for_status()
        return response.json()["count"]

    def search(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/search",
            json={"collection_ids": collection_ids, "query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

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

    def create_evaluation_run(self, collection_id: str, payload: dict[str, Any]) -> str:
        response = self._client.post(f"/api/internal/collections/{collection_id}/evaluation-runs", json=payload)
        response.raise_for_status()
        return response.json()["id"]

    def list_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """Full transcript, oldest first - what score_discussion judges (see #31)."""
        response = self._client.get(f"/api/internal/conversations/{conversation_id}/messages")
        response.raise_for_status()
        return response.json()

    def create_discussion_score(self, conversation_id: str, payload: dict[str, Any]) -> str:
        response = self._client.post(
            f"/api/internal/conversations/{conversation_id}/discussion-scores",
            json=payload,
        )
        response.raise_for_status()
        return response.json()["id"]

    def find_discussion_score(self, conversation_id: str, content_hash: str, llm_model: str) -> str | None:
        """Returns the id of an already-persisted score for this exact (conversation, transcript,
        model) triple, or None - so score_discussion can skip re-judging an unchanged
        conversation with the same model (see content_hash on DiscussionScore)."""
        response = self._client.get(
            f"/api/internal/conversations/{conversation_id}/discussion-scores/exists",
            params={"content_hash": content_hash, "llm_model": llm_model},
        )
        response.raise_for_status()
        return response.json()["id"]

    def set_task_logs(self, celery_task_id: str, logs: str) -> None:
        response = self._client.patch(f"/api/internal/tasks/{celery_task_id}/logs", json={"logs": logs})
        response.raise_for_status()


backend_client = BackendClient()
