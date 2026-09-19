from typing import Any

import httpx

from app.config import settings


class SearxngClient:
    """Talks to a SearXNG instance's public JSON search API - no authentication (SearXNG has
    none by default), same lightweight httpx.Client pattern as BackendClient."""

    def __init__(self) -> None:
        self._client = httpx.Client(base_url=settings.SEARXNG_URL, timeout=15.0)

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        # format=json must be enabled server-side (settings.yml: search.formats) - disabled by
        # default upstream, since it lets any caller scrape results programmatically.
        response = self._client.get("/search", params={"q": query, "format": "json"})
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[:limit]


searxng_client = SearxngClient()
