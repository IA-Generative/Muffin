import time

from loguru import logger

from app.backend_client import backend_client

# In-process, not Redis: one cache per worker process is enough to avoid a DB round-trip on
# every single LLM call within a run, and it self-heals within a minute of an admin publishing
# a new version - no need for cross-process invalidation.
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, str, str]] = {}  # name -> (fetched_at, content, prompt_version_id)


def get_prompt(name: str, fallback: str) -> tuple[str, str | None]:
    """Returns (content, prompt_version_id) for the currently active version of prompt `name`.
    Falls back to `fallback` (the node's own hardcoded default) with prompt_version_id=None on
    any failure - a prompt-versioning outage must never take down a run, same reasoning as
    json_chat's fallback for a malformed LLM response."""
    cached = _cache.get(name)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    prompt = backend_client.get_active_prompt(name)
    if prompt is None:
        logger.warning(f"No active prompt version for '{name}', using hardcoded fallback")
        return fallback, None

    _cache[name] = (time.monotonic(), prompt["content"], prompt["id"])
    return prompt["content"], prompt["id"]
