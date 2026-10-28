from typing import Any

import httpx

from app.config import settings
from app.usage_context import current_usage


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

    def create_evaluation_run(self, collection_id: str, payload: dict[str, Any]) -> str:
        response = self._client.post(f"/api/internal/collections/{collection_id}/evaluation-runs", json=payload)
        response.raise_for_status()
        return response.json()["id"]

    def upload_evaluation_artifacts(
        self, collection_id: str, run_id: str, results_json: bytes, report_html: bytes
    ) -> None:
        """Posts the two promptfoo artifacts of a run - the machine-readable scores and the
        human-readable report - as multipart files. Called right after create_evaluation_run;
        together they are the run's whole persistence (no per-pair rows anymore)."""
        response = self._client.post(
            f"/api/internal/collections/{collection_id}/evaluation-runs/{run_id}/artifacts",
            files={
                "results": ("results.json", results_json, "application/json"),
                "report": ("report.html", report_html, "text/html"),
            },
        )
        response.raise_for_status()

    def find_evaluation_run(self, collection_id: str, content_hash: str, llm_model: str) -> str | None:
        """Returns the id of an already-persisted run for this exact (collection, content, model)
        triple, or None - so run_evaluation can skip re-evaluating an unchanged collection with
        the same model (same dedup strategy as find_discussion_score)."""
        response = self._client.get(
            f"/api/internal/collections/{collection_id}/evaluation-runs/exists",
            params={"content_hash": content_hash, "llm_model": llm_model},
        )
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

    def add_task_logs(self, lines: list[dict]) -> None:
        """A short timeout: the lines are sent again with the next batch, a task never waits on them."""
        response = self._client.post("/api/internal/task-logs", json={"entries": lines}, timeout=5.0)
        response.raise_for_status()

    def add_execution_metric(self, metric: dict) -> None:
        """A short timeout: it is sent from a thread of its own and dropped if it fails, a task never waits on it."""
        response = self._client.post("/api/internal/execution-metrics", json=metric, timeout=5.0)
        response.raise_for_status()


backend_client = BackendClient()
