import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.core.security.worker_auth import require_worker_bearer_key
from app.db import get_db
from app.models.token_usage import TokenUsageKind
from app.schemas.internal_pipeline import LlmUsageContext
from app.services.usage_service import UsageService

# The evaluation judge (promptfoo's factuality grader) only speaks the OpenAI wire
# format - "Authorization: Bearer <key>" and POST /v1/chat/completions - so this
# router exposes exactly that against the LLM hub, keeping the architecture rule
# that a worker never talks to the hub directly.
# The rest of the workers keep using /internal/llm/chat's simpler request shape.
router = APIRouter(
    prefix="/internal/v1",
    tags=["Internal"],
    dependencies=[Depends(require_worker_bearer_key)],
)

# Module attributes (not closed over), same reasoning as app/routers/internal_llm.py:
# tests swap these out with monkeypatch.setattr without a live LLM hub. Duplicated
# from that router (rather than imported) so each keeps its own client instance and
# their tests can monkeypatch them in isolation.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """The subset of the OpenAI chat-completion body the judge actually sends -
    unknown fields (stream, user, seed...) are ignored, pydantic's default."""

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None


class ChatChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str | None = None


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage | None = None


@router.post(
    "/chat/completions",
    summary="Run a chat completion on the worker's behalf, OpenAI wire format - "
    "the evaluation judge's only path to the LLM hub (see #11)",
    response_model=ChatCompletionResponse,
)
async def chat_completions(
    request: ChatCompletionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    # Set by the evaluation worker's generated promptfoo config, so the judge's
    # tokens are attributed to the collection's owner like every other worker call.
    x_collection_id: uuid.UUID | None = Header(default=None),  # noqa: B008
) -> ChatCompletionResponse:
    if _openai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM hub is not configured",
        )
    # Only forward the parameters the caller actually set: the OpenAI SDK treats an
    # explicit None differently from an omitted one.
    kwargs: dict[str, Any] = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    completion = await _openai_client.chat.completions.create(
        model=request.model,
        messages=[{"role": message.role, "content": message.content} for message in request.messages],
        **kwargs,
    )
    usage = completion.usage
    await UsageService(db).record(
        LlmUsageContext(step="evaluation", collection_id=x_collection_id) if x_collection_id else None,
        TokenUsageKind.CHAT,
        request.model,
        usage.prompt_tokens if usage else None,
        usage.completion_tokens if usage else None,
    )
    return ChatCompletionResponse(
        id=getattr(completion, "id", None) or "",
        created=getattr(completion, "created", None) or int(time.time()),
        model=getattr(completion, "model", None) or request.model,
        choices=[
            ChatChoice(
                index=getattr(choice, "index", index),
                message=ChatMessage(
                    role=getattr(choice.message, "role", None) or "assistant",
                    content=choice.message.content or "",
                ),
                finish_reason=getattr(choice, "finish_reason", None),
            )
            for index, choice in enumerate(completion.choices)
        ],
        usage=ChatUsage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.prompt_tokens + usage.completion_tokens,
        )
        if usage
        else None,
    )
