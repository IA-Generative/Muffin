import httpx

from app.config import settings
from app.usage_context import current_usage


class BackendClient:
    """Talks to the backend's /api/internal/* routes, authenticated with the shared
    WORKER_API_KEY instead of a Keycloak session - same pattern as
    worker/document_process/app/backend_client.py. The worker never talks to Postgres or the
    user-facing API directly."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.BACKEND_API_URL,
            headers={"X-API-Key": settings.WORKER_API_KEY},
            timeout=60.0,
        )

    def sync_group(self, source: str, external_id: str, name: str, description: str, member_ids: list[str]) -> dict:
        """Makes Muffin's copy of a group what the other system has (the copy is created if it is not there)."""
        response = self._client.put(
            f"/api/internal/groups/{source}/{external_id}",
            json={"name": name, "description": description, "member_ids": member_ids},
        )
        response.raise_for_status()
        return response.json()

    def sync_collection(self, source: str, external_id: str, body: dict) -> dict:
        """Makes Muffin's copy of a collection what the other system has, and who may read it."""
        response = self._client.put(f"/api/internal/synced-collections/{source}/{external_id}", json=body)
        response.raise_for_status()
        return response.json()

    def sync_document(self, source: str, external_id: str, body: dict) -> dict:
        """Makes Muffin's copy of a file what the other system has, with the chunks it cut it into."""
        response = self._client.put(f"/api/internal/synced-documents/{source}/{external_id}", json=body)
        response.raise_for_status()
        return response.json()

    def list_synced(self, kind: str, source: str) -> list[str]:
        """The ids, in the other system, of what Muffin has copied from it: `groups`, `synced-collections` or
        `synced-documents`."""
        response = self._client.get(f"/api/internal/{kind}/{source}")
        response.raise_for_status()
        return response.json()

    def delete_synced(self, kind: str, source: str, external_id: str) -> None:
        """Drops the copy of what is gone from the other system. Already gone is as good."""
        response = self._client.delete(f"/api/internal/{kind}/{source}/{external_id}")
        if response.status_code != 404:
            response.raise_for_status()

    def embed(self, model: str, text: str) -> list[float]:
        """The embedding of a text, by the same hub and model Muffin embeds a question with."""
        response = self._client.post(
            "/api/internal/llm/embed", json={"model": model, "input": text, "usage": current_usage()}
        )
        response.raise_for_status()
        return response.json()["embedding"]

    def add_task_logs(self, lines: list[dict]) -> None:
        """A short timeout: the lines are sent again with the next batch, a task never waits on them."""
        response = self._client.post("/api/internal/task-logs", json={"entries": lines}, timeout=5.0)
        response.raise_for_status()

    def add_execution_metric(self, metric: dict) -> None:
        """A short timeout: it is sent from a thread of its own and dropped if it fails, a task never waits on it."""
        response = self._client.post("/api/internal/execution-metrics", json=metric, timeout=5.0)
        response.raise_for_status()


backend_client = BackendClient()
