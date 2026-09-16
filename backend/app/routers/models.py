import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI

from app.config import LlmSettings
from app.connectors import redis_connector
from app.core.security.factory import RequestContext, get_current_user
from app.logger import logger
from app.schemas.models import ChatModel, ChatModelsResponse

router = APIRouter(tags=["Models"])

CACHE_KEY = "llm:chat_models"

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


async def _discover_chat_models() -> list[str]:
    available = await _openai_client.models.list()
    candidate_ids = [model.id for model in available.data]
    supports_chat = await asyncio.gather(*(_supports_chat(model_id) for model_id in candidate_ids))
    return sorted(model_id for model_id, supported in zip(candidate_ids, supports_chat, strict=True) if supported)


@router.get(
    "/models",
    summary="List the LLM hub's models that support chat completions",
    response_model=ChatModelsResponse,
)
async def list_models(_: Annotated[RequestContext, Depends(get_current_user)]) -> ChatModelsResponse:
    if _openai_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM hub is not configured")

    cached = redis_connector.client.get(CACHE_KEY)
    if cached is not None:
        chat_model_ids = json.loads(cached)
    else:
        chat_model_ids = await _discover_chat_models()
        redis_connector.client.set(
            CACHE_KEY, json.dumps(chat_model_ids), ex=_llm_settings.CHAT_MODELS_CACHE_TTL_SECONDS
        )

    return ChatModelsResponse(models=[ChatModel(id=model_id) for model_id in chat_model_ids])
