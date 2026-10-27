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
    """Fallback for a hub that doesn't report capabilities: the /models endpoint lists everything
    it serves (embeddings, TTS, vision-only, ...), so the only way to tell them apart is to
    actually try a chat completion. See _reported_operation - the hub we target reports
    capabilities, so this is only reached when it doesn't."""
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


# The hub rate-limits a burst of probes (one chat/embedding call per model) with a per-window
# quota, not a concurrency one: probing every model at once trips it, and the SDK then honours
# the 429's Retry-After, stalling the discovery for a minute. The hub reports each model's
# capabilities in its /models payload, so probing is only a fallback for hubs that don't.
_MODEL_PROBE_CONCURRENCY = 4


def _reported_operation(model: object, operation: str) -> bool | None:
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


async def _discover_models(operation: str, probe: Callable[[str], Awaitable[bool]]) -> list[str]:
    available = await _openai_client.models.list()
    supported: list[str] = []
    unknown: list[str] = []
    for model in available.data:
        reported = _reported_operation(model, operation)
        if reported is None:
            unknown.append(model.id)
        elif reported:
            supported.append(model.id)

    # Only the models the hub didn't report on need a probe, and even then a small pool keeps
    # the burst off the rate limiter.
    if unknown:
        semaphore = asyncio.Semaphore(_MODEL_PROBE_CONCURRENCY)

        async def probe_limited(model_id: str) -> bool:
            async with semaphore:
                return await probe(model_id)

        results = await asyncio.gather(*(probe_limited(model_id) for model_id in unknown))
        supported.extend(model_id for model_id, ok in zip(unknown, results, strict=True) if ok)

    return sorted(supported)


async def _list_models(cache_key: str, operation: str, probe: Callable[[str], Awaitable[bool]]) -> LlmModelsResponse:
    if _openai_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM hub is not configured")

    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        model_ids = json.loads(cached)
    else:
        model_ids = await _discover_models(operation, probe)
        # An empty result means the hub is unreachable or misconfigured, not that it has no
        # models: caching it would break every caller for the whole TTL. Re-probe instead.
        if model_ids:
            redis_connector.client.set(cache_key, json.dumps(model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS)

    return LlmModelsResponse(models=[LlmModel(id=model_id) for model_id in model_ids])


@router.get(
    "/models",
    summary="List the LLM hub's models that support chat completions",
    response_model=LlmModelsResponse,
)
async def list_models(_: Annotated[RequestContext, Depends(get_current_user)]) -> LlmModelsResponse:
    return await _list_models(CHAT_CACHE_KEY, "chat", _supports_chat)


@router.get(
    "/embedding-models",
    summary="List the LLM hub's models that support embeddings",
    response_model=LlmModelsResponse,
)
async def list_embedding_models(_: Annotated[RequestContext, Depends(get_current_user)]) -> LlmModelsResponse:
    return await _list_models(EMBEDDING_CACHE_KEY, "embed", _supports_embeddings)
