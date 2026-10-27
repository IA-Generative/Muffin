import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.connectors import redis_connector
from app.core.security.worker_auth import require_worker_api_key
from app.db import async_session_factory, get_db
from app.models.token_usage import TokenUsageKind
from app.repositories.app_settings_repository import AppSettingsRepository
from app.schemas.internal_pipeline import (
    LlmChatRequest,
    LlmChatResponse,
    LlmEmbedBatchRequest,
    LlmEmbedBatchResponse,
    LlmEmbedRequest,
    LlmEmbedResponse,
)
from app.services.usage_service import UsageService

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
    AsyncOpenAI(
        api_key=_llm_settings.OPENAI_API_KEY,
        base_url=_llm_settings.OPENAI_API_BASE_URL,
        max_retries=8,
    )
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


async def _first_supported_model(cache_key: str, probe) -> str | None:  # noqa: ANN001
    """The alphabetically-first model the hub reports that supports the capability - what a
    pipeline step with no model configured for it falls back to, so processing works out of the
    box instead of silently skipping that step.

    Reads the shared discovery cache (populated by the models router for the UI) when it is warm;
    otherwise probes the hub's models in order and stops at the first success. Probing only until
    the first - rather than sweeping every model at once - is what keeps this off the hub's rate
    limiter: the callers here only ever want the first model, never the whole list (the UI's
    /models route does that, with its own full discovery)."""
    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        model_ids = json.loads(cached)
        return model_ids[0] if model_ids else None
    available = await _openai_client.models.list()
    for model_id in sorted(model.id for model in available.data):
        if await probe(model_id):
            return model_id
    return None


async def _default_chat_model() -> str | None:
    """First chat-capable model the hub reports - what a pipeline step with
    no model configured for it falls back to, so processing works out of the
    box instead of silently skipping that step."""
    if _openai_client is None:
        return None
    return await _first_supported_model(_CHAT_MODELS_CACHE_KEY, _supports_chat)


async def _default_embedding_model(db: AsyncSession) -> str | None:
    """The admin-configured global embedding model (app_settings.embedding_model)
    if one was set, otherwise the hub's first embedding-capable model. Always
    global, never per-collection - every collection's description embedding
    (the "collections" Qdrant index, §124) must live in the same space."""
    app_settings = await AppSettingsRepository(db).get()
    if app_settings and app_settings.embedding_model:
        return app_settings.embedding_model
    if _openai_client is None:
        return None
    return await _first_supported_model(_EMBEDDING_MODELS_CACHE_KEY, _supports_embeddings)


@router.post(
    "/llm/chat",
    summary="Run a chat completion on the worker's behalf",
    response_model=LlmChatResponse,
)
async def chat(request: LlmChatRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> LlmChatResponse:
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
    # Every worker LLM call goes through here - the one place consumption can't be missed.
    await UsageService(db).record(
        request.usage,
        TokenUsageKind.CHAT,
        request.model,
        usage.prompt_tokens if usage else None,
        usage.completion_tokens if usage else None,
    )
    return LlmChatResponse(
        content=completion.choices[0].message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
    )


@router.post(
    "/llm/chat-stream",
    summary="Run a chat completion on the worker's behalf, streamed as it is written (one JSON object per line)",
)
async def chat_stream(request: LlmChatRequest) -> StreamingResponse:
    """Same call as `chat`, but the worker gets the text as the model writes it - {"delta": "..."} lines,
    then a last {"done": true, "prompt_tokens", "completion_tokens"} line. What the worker does with the
    partial text (showing it to the user while the answer is still being written) is its business."""
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    stream = await _openai_client.chat.completions.create(
        model=request.model,
        messages=[{"role": message.role, "content": message.content} for message in request.messages],
        max_tokens=request.max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )

    async def lines() -> AsyncIterator[str]:
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for chunk in stream:
            if chunk.usage:
                prompt_tokens, completion_tokens = chunk.usage.prompt_tokens, chunk.usage.completion_tokens
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({"delta": chunk.choices[0].delta.content}) + "\n"
        # Own session: the request's would be closed by the time a streamed body has been sent.
        async with async_session_factory() as db:
            await UsageService(db).record(
                request.usage, TokenUsageKind.CHAT, request.model, prompt_tokens, completion_tokens
            )
        yield json.dumps({"done": True, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


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
async def embed(request: LlmEmbedRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> LlmEmbedResponse:
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    result = await _openai_client.embeddings.create(model=request.model, input=request.input)
    usage = getattr(result, "usage", None)
    await UsageService(db).record(
        request.usage, TokenUsageKind.EMBEDDING, request.model, usage.prompt_tokens if usage else None, 0
    )
    return LlmEmbedResponse(embedding=result.data[0].embedding)


@router.post(
    "/llm/embed-batch",
    summary="Embed several texts in one call on the worker's behalf (an index rebuild, #12)",
    response_model=LlmEmbedBatchResponse,
)
async def embed_batch(
    request: LlmEmbedBatchRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> LlmEmbedBatchResponse:
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    result = await _openai_client.embeddings.create(model=request.model, input=request.inputs)
    usage = getattr(result, "usage", None)
    await UsageService(db).record(
        request.usage, TokenUsageKind.EMBEDDING, request.model, usage.prompt_tokens if usage else None, 0
    )
    # The hub answers in input order, but says so with an index: trusted over the list order.
    ordered = sorted(result.data, key=lambda item: item.index)
    return LlmEmbedBatchResponse(embeddings=[item.embedding for item in ordered])


@router.get(
    "/llm/default-embedding-model",
    summary="The global embedding model for collection-description embeddings (admin-configured, or the hub's first "
    "embedding-capable model)",
)
async def default_embedding_model(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | None]:
    return {"model": await _default_embedding_model(db)}
