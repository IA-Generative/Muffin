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

    def set_task_logs(self, celery_task_id: str, logs: str) -> None:
        response = self._client.patch(f"/api/internal/tasks/{celery_task_id}/logs", json={"logs": logs})
        response.raise_for_status()


backend_client = BackendClient()
