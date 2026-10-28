"""Discovery of the LLM hub's models, shared by the UI router (app/routers/models.py), the
worker's internal router (app/routers/internal_llm.py) and the backend services
(app/services/embedding_model_lookup.py).

The hub's /models payload reports each model's capabilities (capabilities.operations: chat,
embed, ...), so discovery reads those instead of probing. Probing every model trips the hub's
per-window rate limiter, and the SDK then honours the 429's Retry-After, stalling discovery for
a minute. Probing remains only as a fallback for a hub that doesn't report capabilities.

The client is passed in rather than owned here: each caller keeps its own module-level client so
its tests can monkeypatch it in isolation.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from app.connectors import redis_connector

Probe = Callable[[str], Awaitable[bool]]

# A small pool keeps the fallback probe burst off the hub's rate limiter.
_PROBE_CONCURRENCY = 4


def reported_operation(model: object, operation: str) -> bool | None:
    """Whether the hub reports this model as serving `operation` (chat, embed, ...), read from
    the /models payload's capabilities.operations. None when the hub doesn't report capabilities
    - the caller then falls back to probing."""
    capabilities = getattr(model, "capabilities", None)
    if not isinstance(capabilities, dict):
        return None
    operations = capabilities.get("operations")
    if not isinstance(operations, list):
        return None
    return operation in operations


async def discover_models(client: AsyncOpenAI, operation: str, probe: Probe) -> list[str]:
    """Every model the hub reports as serving `operation`, sorted."""
    available = await client.models.list()
    supported: list[str] = []
    unknown: list[str] = []
    for model in available.data:
        reported = reported_operation(model, operation)
        if reported is None:
            unknown.append(model.id)
        elif reported:
            supported.append(model.id)

    # Only the models the hub didn't report on need a probe, and even then a small pool keeps
    # the burst off the rate limiter.
    if unknown:
        semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

        async def probe_limited(model_id: str) -> bool:
            async with semaphore:
                return await probe(model_id)

        results = await asyncio.gather(*(probe_limited(model_id) for model_id in unknown))
        supported.extend(model_id for model_id, ok in zip(unknown, results, strict=True) if ok)

    return sorted(supported)


async def first_supported_model(client: AsyncOpenAI, operation: str, probe: Probe) -> str | None:
    """The alphabetically-first model the hub reports as serving `operation` - what a pipeline
    step with no model configured for it falls back to, so processing works out of the box
    instead of silently skipping that step."""
    available = await client.models.list()
    for model in sorted(available.data, key=lambda model: model.id):
        reported = reported_operation(model, operation)
        if reported is True:
            return model.id
        if reported is None and await probe(model.id):
            return model.id
    return None


async def cached_models(
    client: AsyncOpenAI, cache_key: str, operation: str, probe: Probe, ttl_seconds: int
) -> list[str]:
    """`discover_models`, memoised in Redis. An empty result means the hub is unreachable or
    misconfigured, not that it has no models: caching it would break every caller for the whole
    TTL, so it is re-probed instead."""
    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        return json.loads(cached)
    model_ids = await discover_models(client, operation, probe)
    if model_ids:
        redis_connector.client.set(cache_key, json.dumps(model_ids), ex=ttl_seconds)
    return model_ids
