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
            timeout=30.0,
        )

    def get_document(self, document_id: str) -> dict[str, Any]:
        response = self._client.get(f"/api/internal/documents/{document_id}")
        response.raise_for_status()
        return response.json()

    def update_status(
        self, document_id: str, status: str, progress: int | None = None, summary: str | None = None
    ) -> None:
        body: dict[str, Any] = {"status": status}
        if progress is not None:
            body["progress"] = progress
        if summary is not None:
            body["summary"] = summary
        response = self._client.patch(f"/api/internal/documents/{document_id}/status", json=body)
        response.raise_for_status()

    def add_page(self, document_id: str, page_number: int, content: str, screenshot: str | None = None) -> None:
        response = self._client.post(
            f"/api/internal/documents/{document_id}/pages",
            json={"page_number": page_number, "content": content, "screenshot": screenshot},
        )
        response.raise_for_status()

    def add_chunk(
        self, document_id: str, index: int, text: str, token_count: int, extras: dict[str, Any] | None = None
    ) -> None:
        response = self._client.post(
            f"/api/internal/documents/{document_id}/chunks",
            json={"index": index, "text": text, "token_count": token_count, "extras": extras},
        )
        response.raise_for_status()


backend_client = BackendClient()
