from typing import Any

import httpx

from app.agent.config import settings


class SearxngClient:
    """Talks to a SearXNG instance's public JSON search API - no authentication (SearXNG has
    none by default), same lightweight httpx pattern as BackendClient."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    @property
    def _client(self) -> httpx.AsyncClient:
        # Made when first used, inside the loop that runs it: an async client belongs to one loop.
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=settings.SEARXNG_URL, timeout=15.0)
        return self._http

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        # format=json must be enabled server-side (settings.yml: search.formats) - disabled by
        # default upstream, since it lets any caller scrape results programmatically.
        response = await self._client.get("/search", params={"q": query, "format": "json"})
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[:limit]


searxng_client = SearxngClient()
