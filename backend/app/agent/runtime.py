"""The agent runs in the backend, in a thread of its own, and reaches the backend's own code through its event loop.

A run is a background task of the backend (see runner.py): its graph is made of synchronous nodes, which a thread runs
so that they never block the loop that serves the users. What a node asks of the backend - a route, a stream - is a
coroutine it hands to that loop and waits for."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """The backend's loop, taken when the first run starts."""
    global _loop
    _loop = loop


def run_on_loop(coroutine: Any, timeout: float | None = None) -> Any:
    """Runs a coroutine on the backend's loop from a thread of a run, and returns what it returned."""
    if _loop is None or _loop.is_closed():
        coroutine.close()
        raise RuntimeError("The agent's runtime is not started")
    return asyncio.run_coroutine_threadsafe(coroutine, _loop).result(timeout)


def iterate_on_loop[T](stream: AsyncIterator[T]) -> Iterator[T]:
    """What an async generator yields, one item at a time, from a thread of a run."""

    async def next_item() -> tuple[bool, Any]:
        try:
            return True, await stream.__anext__()
        except StopAsyncIteration:
            return False, None

    while True:
        more, item = run_on_loop(next_item())
        if not more:
            return
        yield item


class InProcessClient:
    """The few methods of an httpx client the agent uses, answered by the backend itself: the requests go through its
    own routes - so the logic of each stays where it is, and nothing is copied - without leaving the process.

    The worker key is still required, as it is for every /api/internal route: it is what says the caller is the
    agent."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _async_client(self) -> httpx.AsyncClient:
        if self._client is None:
            from app.main import app  # imported late: the application imports the runner that imports this

            self._client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://backend.internal",
                headers={"X-API-Key": self._api_key},
            )
        return self._client

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.pop("timeout", None)
        return run_on_loop(self._async_client().request(method, url, **kwargs))

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)
