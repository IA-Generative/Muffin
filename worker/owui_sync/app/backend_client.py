import httpx

from app.config import settings


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

    def add_task_logs(self, lines: list[dict]) -> None:
        """A short timeout: the lines are sent again with the next batch, a task never waits on them."""
        response = self._client.post("/api/internal/task-logs", json={"entries": lines}, timeout=5.0)
        response.raise_for_status()

    def add_execution_metric(self, metric: dict) -> None:
        """A short timeout: it is sent from a thread of its own and dropped if it fails, a task never waits on it."""
        response = self._client.post("/api/internal/execution-metrics", json=metric, timeout=5.0)
        response.raise_for_status()


backend_client = BackendClient()
