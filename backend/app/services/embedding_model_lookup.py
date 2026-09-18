import asyncio
import json

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.connectors import redis_connector
from app.repositories.app_settings_repository import AppSettingsRepository

# Same module-level-client pattern as app/routers/models.py and app/routers/internal_llm.py -
# duplicated (not imported) so each caller's tests can monkeypatch its own client in isolation.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)

# Same cache key as app/routers/internal_llm.py and app/routers/models.py - whichever of the
# three populates it first serves the others for free.
_EMBEDDING_MODELS_CACHE_KEY = "llm:embedding_models"


async def _supports_embeddings(model_id: str) -> bool:
    try:
        await _openai_client.embeddings.create(model=model_id, input="ping")
        return True
    except Exception:
        return False


async def _discover_embedding_models() -> list[str]:
    cached = redis_connector.client.get(_EMBEDDING_MODELS_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)
    available = await _openai_client.models.list()
    candidate_ids = [model.id for model in available.data]
    supported = await asyncio.gather(*(_supports_embeddings(model_id) for model_id in candidate_ids))
    model_ids = sorted(model_id for model_id, ok in zip(candidate_ids, supported, strict=True) if ok)
    redis_connector.client.set(
        _EMBEDDING_MODELS_CACHE_KEY, json.dumps(model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS
    )
    return model_ids


async def default_embedding_model(db: AsyncSession) -> str | None:
    """The admin-configured global embedding model (app_settings.embedding_model) if one was
    set, otherwise the hub's first actually embedding-capable model - never a hardcoded model
    name, since the hub might not be real OpenAI and might not recognize it at all."""
    app_settings = await AppSettingsRepository(db).get()
    if app_settings and app_settings.embedding_model:
        return app_settings.embedding_model
    if _openai_client is None:
        return None
    model_ids = await _discover_embedding_models()
    return model_ids[0] if model_ids else None
