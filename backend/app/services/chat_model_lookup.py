import asyncio
import json

from openai import AsyncOpenAI

from app.config import LlmSettings
from app.connectors import redis_connector

# Same module-level-client pattern as app/services/embedding_model_lookup.py: duplicated, not imported, so each
# caller's tests can monkeypatch its own client in isolation.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)

# Same cache key as app/routers/models.py and app/routers/internal_llm.py.
_CHAT_MODELS_CACHE_KEY = "llm:chat_models"


async def _supports_chat(model_id: str) -> bool:
    try:
        await _openai_client.chat.completions.create(
            model=model_id, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        return True
    except Exception:
        return False


async def default_chat_model() -> str | None:
    """The hub's first chat-capable model - never a hardcoded name, the hub might not recognize it."""
    if _openai_client is None:
        return None
    cached = redis_connector.client.get(_CHAT_MODELS_CACHE_KEY)
    if cached is not None:
        model_ids = json.loads(cached)
    else:
        available = await _openai_client.models.list()
        candidates = [model.id for model in available.data]
        supported = await asyncio.gather(*(_supports_chat(model_id) for model_id in candidates))
        model_ids = sorted(model_id for model_id, ok in zip(candidates, supported, strict=True) if ok)
        redis_connector.client.set(
            _CHAT_MODELS_CACHE_KEY, json.dumps(model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS
        )
    return model_ids[0] if model_ids else None
