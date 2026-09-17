from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI

from app.config import LlmSettings
from app.core.security.worker_auth import require_worker_api_key
from app.schemas.internal_pipeline import LlmChatRequest, LlmChatResponse

# Not user-facing: the worker's only path to the LLM hub, so it never needs
# its own OPENAI_API_KEY. Authenticated with the shared worker API key.
router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])

# Module attributes (not closed over), same reasoning as app/routers/models.py:
# tests swap these out with monkeypatch.setattr without a live LLM hub.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)


@router.post("/llm/chat", summary="Run a chat completion on the worker's behalf", response_model=LlmChatResponse)
async def chat(request: LlmChatRequest) -> LlmChatResponse:
    if _openai_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM hub is not configured")
    completion = await _openai_client.chat.completions.create(
        model=request.model,
        messages=[{"role": message.role, "content": message.content} for message in request.messages],
        max_tokens=request.max_tokens,
    )
    return LlmChatResponse(content=completion.choices[0].message.content or "")
