import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI

from app.config import LlmSettings
from app.connectors import redis_connector
from app.core.security.factory import RequestContext, get_current_user
from app.logger import logger
from app.schemas.models import LlmModel, LlmModelsResponse

router = APIRouter(tags=["Models"])

CHAT_CACHE_KEY = "llm:chat_models"
EMBEDDING_CACHE_KEY = "llm:embedding_models"

# Exposed as module attributes (rather than closed over) so tests can swap
# them out with monkeypatch.setattr without a live LLM hub or Redis.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)


async def _supports_chat(model_id: str) -> bool:
    """The hub's /models endpoint lists everything it serves (embeddings, TTS,
    vision-only, ...), not just chat models - the only reliable way to tell
    them apart is to actually try a chat completion."""
    try:
        await _openai_client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return True
    except Exception as error:
        logger.debug(f"Model '{model_id}' is not chat-capable: {error}")
        return False


async def _supports_embeddings(model_id: str) -> bool:
    try:
        await _openai_client.embeddings.create(model=model_id, input="ping")
        return True
    except Exception as error:
        logger.debug(f"Model '{model_id}' is not embedding-capable: {error}")
        return False


async def _discover_models(probe: Callable[[str], Awaitable[bool]]) -> list[str]:
    available = await _openai_client.models.list()
    candidate_ids = [model.id for model in available.data]
    supported = await asyncio.gather(*(probe(model_id) for model_id in candidate_ids))
    return sorted(model_id for model_id, ok in zip(candidate_ids, supported, strict=True) if ok)


async def _list_models(cache_key: str, probe: Callable[[str], Awaitable[bool]]) -> LlmModelsResponse:
    if _openai_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM hub is not configured")

    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        model_ids = json.loads(cached)
    else:
        model_ids = await _discover_models(probe)
        redis_connector.client.set(cache_key, json.dumps(model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS)

    return LlmModelsResponse(models=[LlmModel(id=model_id) for model_id in model_ids])


@router.get(
    "/models",
    summary="List the LLM hub's models that support chat completions",
    response_model=LlmModelsResponse,
)
async def list_models(_: Annotated[RequestContext, Depends(get_current_user)]) -> LlmModelsResponse:
    return await _list_models(CHAT_CACHE_KEY, _supports_chat)


@router.get(
    "/embedding-models",
    summary="List the LLM hub's models that support embeddings",
    response_model=LlmModelsResponse,
)
async def list_embedding_models(_: Annotated[RequestContext, Depends(get_current_user)]) -> LlmModelsResponse:
    return await _list_models(EMBEDDING_CACHE_KEY, _supports_embeddings)
