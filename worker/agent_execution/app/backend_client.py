from typing import Any

import httpx

from app.config import settings


class EditRequestRefused(Exception):
    """The backend declined to start (or follow) an edit of a living document - `message` is in
    French and fit to tell the user, `code` is the machine-readable reason when there is one
    (draft_exists, document_locked...)."""

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _refusal(error: httpx.HTTPStatusError) -> EditRequestRefused:
    """What the backend's error body says, as an EditRequestRefused. Its 409s carry
    {"code", "message"} (or, for a locked document, who holds the lock); the rest is a plain string."""
    status = error.response.status_code
    try:
        detail = error.response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict):
        code = detail.get("code")
        if code == "document_locked":
            who = detail.get("locked_by_display") or "quelqu'un d'autre"
            return EditRequestRefused(status, code, f"Ce document est en cours de modification par {who}.")
        return EditRequestRefused(status, code, str(detail.get("message") or "La modification a été refusée."))
    if status == 403:
        return EditRequestRefused(status, None, "Vous n'avez pas le droit de modifier ce document.")
    if status == 404:
        return EditRequestRefused(status, None, "Ce document est introuvable.")
    return EditRequestRefused(status, None, f"La demande de modification a échoué ({status}).")


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
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        current_activity: str | None = None,
    ) -> None:
        response = self._client.patch(
            f"/api/internal/runs/{run_id}/status",
            json={
                "status": status,
                "current_node": current_node,
                "current_activity": current_activity,
            },
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

    def set_run_result(
        self,
        run_id: str,
        answer: str,
        citations: list[dict[str, Any]],
        grounding_valid: bool | None = None,
        grounding_unsupported_claims: list[str] | None = None,
        grounding_research_count: int | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        edit_proposal: dict[str, Any] | None = None,
    ) -> None:
        response = self._client.patch(
            f"/api/internal/runs/{run_id}/result",
            json={
                "answer": answer,
                "citations": citations,
                "grounding_valid": grounding_valid,
                "grounding_unsupported_claims": grounding_unsupported_claims,
                "grounding_research_count": grounding_research_count,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "edit_proposal": edit_proposal,
            },
        )
        response.raise_for_status()

    def list_editable_documents(self, run_id: str) -> list[dict[str, Any]]:
        """The living documents the run's user may change - computed backend-side from the run's own
        snapshot (user, groups, administrator flag), never from anything this worker supplies."""
        response = self._client.get(f"/api/internal/runs/{run_id}/editable-documents")
        response.raise_for_status()
        return response.json()

    def create_edit_request(self, run_id: str, document_id: str, prompt: str) -> dict[str, Any]:
        """Delegates an edit to the editing agent: the backend creates the draft (and the document
        lock) and sends the job. Returns the draft's state; raises EditRequestRefused when it
        declines (not allowed, locked by someone, a proposal already pending...)."""
        try:
            response = self._client.post(
                f"/api/internal/runs/{run_id}/edit-requests", json={"document_id": document_id, "prompt": prompt}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise _refusal(error) from error
        return response.json()

    def get_edit_request(self, run_id: str, document_id: str) -> dict[str, Any]:
        """Where the delegated edit stands. Reading it also keeps the draft (and its lock) alive."""
        try:
            response = self._client.get(f"/api/internal/runs/{run_id}/edit-requests/{document_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise _refusal(error) from error
        return response.json()

    def set_run_error(self, run_id: str, error: str) -> None:
        response = self._client.patch(f"/api/internal/runs/{run_id}/error", json={"error": error})
        response.raise_for_status()

    def add_run_event(
        self,
        run_id: str,
        type_: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        response = self._client.post(
            f"/api/internal/runs/{run_id}/events",
            json={"type": type_, "data": data, "task_id": task_id},
        )
        response.raise_for_status()

    def list_accessible_collections(self, user_id: str, groups: list[str] | None = None) -> list[dict[str, Any]]:
        # groups: this user's Keycloak groups at run creation time (Run.user_groups) - without
        # it, a collection shared to a group the user belongs to (see CollectionRepository.
        # list_all_accessible) would be invisible to the agent's VDB routing.
        response = self._client.get(
            f"/api/internal/users/{user_id}/accessible-collections",
            params={"groups": groups or []},
        )
        response.raise_for_status()
        return response.json()

    def search(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/search",
            json={"collection_ids": collection_ids, "query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def search_qa(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/qa-search",
            json={"collection_ids": collection_ids, "query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def search_summaries(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/api/internal/summary-search",
            json={"collection_ids": collection_ids, "query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def search_collections(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        """Vector search over collection *descriptions* (§ VDB routing pre-filter, #124) -
        restricted to `collection_ids`, so the backend never returns a collection the caller
        didn't already establish the user can access."""
        response = self._client.post(
            "/api/internal/collections/search",
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

    def llm_chat_with_usage(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> dict[str, Any]:
        """Same as llm_chat but also returns token usage (prompt_tokens, completion_tokens).
        Used by generate_answer to record per-message token stats on the assistant message.
        """
        response = self._client.post(
            "/api/internal/llm/chat",
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
        )
        response.raise_for_status()
        data = response.json()
        return {
            "content": data["content"],
            "prompt_tokens": data.get("prompt_tokens"),
            "completion_tokens": data.get("completion_tokens"),
        }

    def get_default_chat_model(self) -> str | None:
        response = self._client.get("/api/internal/llm/default-chat-model")
        response.raise_for_status()
        return response.json()["model"]

    def list_collection_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        response = self._client.get(f"/api/internal/users/{user_id}/collections/{collection_id}/documents")
        response.raise_for_status()
        return response.json()

    def list_tabular_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        """Lists tabular documents in a collection that the agent can query with DuckDB.
        Returns id/name/storage_key/format + the full tabular profile (columns, classification)
        so the SQL generator has the schema without an extra round-trip."""
        response = self._client.get(f"/api/internal/users/{user_id}/collections/{collection_id}/tabular-documents")
        response.raise_for_status()
        return response.json()

    def get_document_page(self, user_id: str, document_id: str, page_number: int) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/users/{user_id}/documents/{document_id}/pages/{page_number}")
        response.raise_for_status()
        return response.json()

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        response = self._client.patch(
            f"/api/internal/conversations/{conversation_id}/title",
            json={"title": title},
        )
        response.raise_for_status()

    def get_active_prompt(self, name: str) -> dict[str, Any] | None:
        """None on a 404 (no active version yet for this name) as well as any other failure -
        callers fall back to their own hardcoded default rather than crash the run over the
        prompt-versioning service being unavailable."""
        try:
            response = self._client.get(f"/api/internal/prompts/{name}/active")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return None

    def add_prompt_usages(self, run_id: str, prompt_version_ids: list[str]) -> None:
        response = self._client.post(
            f"/api/internal/prompts/runs/{run_id}/usages",
            json={"prompt_version_ids": prompt_version_ids},
        )
        response.raise_for_status()


backend_client = BackendClient()
