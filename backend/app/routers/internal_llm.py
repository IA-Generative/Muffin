import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.connectors import redis_connector
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.app_settings_repository import AppSettingsRepository
from app.schemas.internal_pipeline import (
    LlmChatRequest,
    LlmChatResponse,
    LlmEmbedRequest,
    LlmEmbedResponse,
)

# Not user-facing: the worker's only path to the LLM hub, so it never needs
# its own OPENAI_API_KEY. Authenticated with the shared worker API key.
router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)

# Module attributes (not closed over), same reasoning as app/routers/models.py:
# tests swap these out with monkeypatch.setattr without a live LLM hub.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)

# Same cache keys as app/routers/models.py's model discovery - reusing them
# means whichever of the two populates one first serves the other for free.
# Duplicated here (rather than imported) because that router keeps its own
# client instance so its tests can monkeypatch it in isolation.
_CHAT_MODELS_CACHE_KEY = "llm:chat_models"
_EMBEDDING_MODELS_CACHE_KEY = "llm:embedding_models"


async def _supports_chat(model_id: str) -> bool:
    try:
        await _openai_client.chat.completions.create(
            model=model_id, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        return True
    except Exception:
        return False


async def _supports_embeddings(model_id: str) -> bool:
    try:
        await _openai_client.embeddings.create(model=model_id, input="ping")
        return True
    except Exception:
        return False


async def _discover_models(cache_key: str, probe) -> list[str]:  # noqa: ANN001
    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        return json.loads(cached)
    available = await _openai_client.models.list()
    candidate_ids = [model.id for model in available.data]
    supported = await asyncio.gather(*(probe(model_id) for model_id in candidate_ids))
    model_ids = sorted(model_id for model_id, ok in zip(candidate_ids, supported, strict=True) if ok)
    redis_connector.client.set(cache_key, json.dumps(model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS)
    return model_ids


async def _default_chat_model() -> str | None:
    """First chat-capable model the hub reports - what a pipeline step with
    no model configured for it falls back to, so processing works out of the
    box instead of silently skipping that step."""
    if _openai_client is None:
        return None
    model_ids = await _discover_models(_CHAT_MODELS_CACHE_KEY, _supports_chat)
    return model_ids[0] if model_ids else None


async def _default_embedding_model(db: AsyncSession) -> str | None:
    """The admin-configured global embedding model (app_settings.embedding_model)
    if one was set, otherwise the hub's first embedding-capable model. Always
    global, never per-collection - see CollectionDescriptionEmbedding."""
    app_settings = await AppSettingsRepository(db).get()
    if app_settings and app_settings.embedding_model:
        return app_settings.embedding_model
    if _openai_client is None:
        return None
    model_ids = await _discover_models(_EMBEDDING_MODELS_CACHE_KEY, _supports_embeddings)
    return model_ids[0] if model_ids else None


@router.post(
    "/llm/chat",
    summary="Run a chat completion on the worker's behalf",
    response_model=LlmChatResponse,
)
async def chat(request: LlmChatRequest) -> LlmChatResponse:
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    completion = await _openai_client.chat.completions.create(
        model=request.model,
        messages=[{"role": message.role, "content": message.content} for message in request.messages],
        max_tokens=request.max_tokens,
    )
    usage = completion.usage
    return LlmChatResponse(
        content=completion.choices[0].message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
    )


@router.get(
    "/llm/default-chat-model",
    summary="The hub's first chat-capable model, for a pipeline step with no model configured",
)
async def default_chat_model() -> dict[str, str | None]:
    return {"model": await _default_chat_model()}


@router.post(
    "/llm/embed",
    summary="Embed a piece of text on the worker's behalf",
    response_model=LlmEmbedResponse,
)
async def embed(request: LlmEmbedRequest) -> LlmEmbedResponse:
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    result = await _openai_client.embeddings.create(model=request.model, input=request.input)
    return LlmEmbedResponse(embedding=result.data[0].embedding)


@router.get(
    "/llm/default-embedding-model",
    summary="The global embedding model for collection-description embeddings (admin-configured, or the hub's first "
    "embedding-capable model)",
)
async def default_embedding_model(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | None]:
    return {"model": await _default_embedding_model(db)}
