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

    def get_run(self, run_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/runs/{run_id}")
        response.raise_for_status()
        return response.json()

    def update_run_status(
        self, run_id: str, status: str, current_node: str | None = None, current_activity: str | None = None
    ) -> None:
        response = self._client.patch(
            f"/api/internal/runs/{run_id}/status",
            json={"status": status, "current_node": current_node, "current_activity": current_activity},
        )
        response.raise_for_status()

    def update_run_state(
        self,
        run_id: str,
        research_plan: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        pending_human_action: dict[str, Any] | None = None,
        plan_version: int | None = None,
        replan_count: int | None = None,
    ) -> None:
        response = self._client.patch(
            f"/api/internal/runs/{run_id}/state",
            json={
                "research_plan": research_plan,
                "budget": budget,
                "pending_human_action": pending_human_action,
                "plan_version": plan_version,
                "replan_count": replan_count,
            },
        )
        response.raise_for_status()

    def set_run_result(self, run_id: str, answer: str, citations: list[dict[str, Any]]) -> None:
        response = self._client.patch(
            f"/api/internal/runs/{run_id}/result", json={"answer": answer, "citations": citations}
        )
        response.raise_for_status()

    def set_run_error(self, run_id: str, error: str) -> None:
        response = self._client.patch(f"/api/internal/runs/{run_id}/error", json={"error": error})
        response.raise_for_status()

    def add_run_event(
        self, run_id: str, type_: str, data: dict[str, Any] | None = None, task_id: str | None = None
    ) -> None:
        response = self._client.post(
            f"/api/internal/runs/{run_id}/events", json={"type": type_, "data": data, "task_id": task_id}
        )
        response.raise_for_status()

    def list_accessible_collections(self, user_id: str, groups: list[str] | None = None) -> list[dict[str, Any]]:
        # groups: this user's Keycloak groups at run creation time (Run.user_groups) - without
        # it, a collection shared to a group the user belongs to (see CollectionRepository.
        # list_all_accessible) would be invisible to the agent's VDB routing.
        response = self._client.get(
            f"/api/internal/users/{user_id}/accessible-collections", params={"groups": groups or []}
        )
        response.raise_for_status()
        return response.json()

    def search(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/search", json={"collection_ids": collection_ids, "query": query, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def search_qa(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/qa-search", json={"collection_ids": collection_ids, "query": query, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def search_summaries(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/summary-search", json={"collection_ids": collection_ids, "query": query, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        response = self._client.post(
            "/api/internal/llm/chat", json={"model": model, "messages": messages, "max_tokens": max_tokens}
        )
        response.raise_for_status()
        return response.json()["content"]

    def get_default_chat_model(self) -> str | None:
        response = self._client.get("/api/internal/llm/default-chat-model")
        response.raise_for_status()
        return response.json()["model"]

    def list_collection_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        response = self._client.get(f"/api/internal/users/{user_id}/collections/{collection_id}/documents")
        response.raise_for_status()
        return response.json()

    def get_document_page(self, user_id: str, document_id: str, page_number: int) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/users/{user_id}/documents/{document_id}/pages/{page_number}")
        response.raise_for_status()
        return response.json()

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        response = self._client.patch(f"/api/internal/conversations/{conversation_id}/title", json={"title": title})
        response.raise_for_status()


backend_client = BackendClient()
