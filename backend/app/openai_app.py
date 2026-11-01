"""The OpenAI-compatible API (#513), under /v1: `GET /v1/models` and `POST /v1/chat/completions`.

An application of its own, mounted like the MCP server: it answers in OpenAI's format - errors included - and takes a
personal API key (`Authorization: Bearer sk-muffin-…`, scope `chat`) and nothing else: not the session cookie, which a
browser sends on its own to any page, and not a Keycloak token."""

import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.core.api_keys import PREFIX
from app.core.security.factory import RequestContext
from app.db import async_session_factory, get_db
from app.models.api_key import SCOPE_CHAT
from app.schemas.openai_api import ChatCompletionRequest, ModelList, ModelOut
from app.services import api_key_service, openai_chat_service
from app.services.api_key_service import ApiKeyRateLimitedError, ApiKeyService, InvalidApiKeyError
from app.services.openai_chat_service import (
    AnswerStream,
    Final,
    Numbering,
    OpenAiChatService,
    OpenAiError,
    sources_markdown,
    sources_of,
)

openai_app = FastAPI(title="Muffin - OpenAI-compatible API", docs_url=None, redoc_url=None, openapi_url=None)

_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@openai_app.exception_handler(OpenAiError)
async def _openai_error(_request: Request, error: OpenAiError) -> JSONResponse:
    headers = {"Retry-After": "60"} if error.status_code == 429 else None
    return JSONResponse(error.body(), status_code=error.status_code, headers=headers)


@openai_app.exception_handler(RequestValidationError)
async def _invalid_body(_request: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0] if error.errors() else {}
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = f"Invalid request: {where}: {first.get('msg', 'invalid')}" if where else "Invalid request"
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "code": "invalid_request", "param": where}},
        status_code=400,
    )


async def api_caller(authorization: Annotated[str | None, Header()] = None) -> RequestContext:
    """Whom the key stands for. Why a key is refused is never told: unknown, revoked, expired, or not for this."""
    if not api_key_service._settings.enabled:
        raise OpenAiError(503, "API keys are not enabled on this server", "api_error", "api_keys_disabled")
    if not authorization or not authorization.startswith(f"Bearer {PREFIX}"):
        raise OpenAiError(401, "Incorrect API key provided", "invalid_request_error", "invalid_api_key")
    try:
        async with async_session_factory() as db:
            return await ApiKeyService(db).authenticate(authorization.removeprefix("Bearer "), SCOPE_CHAT)
    except ApiKeyRateLimitedError:
        raise OpenAiError(429, "Too many requests: slow down", "rate_limit_error", "rate_limit_exceeded") from None
    except InvalidApiKeyError:
        raise OpenAiError(401, "Incorrect API key provided", "invalid_request_error", "invalid_api_key") from None


CallerDep = Annotated[RequestContext, Depends(api_caller)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@openai_app.get("/models", response_model=ModelList)
async def list_models(caller: CallerDep, db: DbDep) -> ModelList:
    return await OpenAiChatService(db).list_models(caller)


@openai_app.get("/models/{model_id:path}", response_model=ModelOut)
async def get_model(model_id: str, caller: CallerDep, db: DbDep) -> ModelOut:
    return await OpenAiChatService(db).get_model(caller, model_id)


def _usage(result: Final) -> dict[str, int] | None:
    if result.prompt_tokens is None and result.completion_tokens is None:
        return None
    prompt, completion = result.prompt_tokens or 0, result.completion_tokens or 0
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def _chunk(
    completion_id: str, model: str, created: int, delta: dict[str, Any], finish: str | None, **extra: Any
) -> str:
    body = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        **extra,
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


@openai_app.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    caller: CallerDep,
    db: DbDep,
    x_muffin_conversation: Annotated[str | None, Header()] = None,
) -> Any:
    openai_chat_service.acquire_slot(caller.user_id)
    try:
        run_id, conversation_id = await OpenAiChatService(db).start(caller, body, x_muffin_conversation)
    except BaseException:
        openai_chat_service.release_slot(caller.user_id)
        raise
    completion_id = f"chatcmpl-{run_id.hex}"
    created = int(time.time())
    steps = bool(body.muffin and body.muffin.steps)
    if body.stream:
        return StreamingResponse(
            _stream(request, caller, body, run_id, completion_id, created, steps),
            media_type="text/event-stream",
            headers=_STREAM_HEADERS,
            background=BackgroundTask(openai_chat_service.release_slot, caller.user_id),
        )
    try:
        async for event in openai_chat_service.follow(run_id, request.is_disconnected):
            if event.kind == "end":
                break
        else:
            await openai_chat_service.cancel(run_id, caller)
            raise OpenAiError(499, "The client closed the request", "api_error", "client_closed")
        result = await openai_chat_service.final_of(run_id, caller)
        openai_chat_service.check_final(result)
    except TimeoutError:
        await openai_chat_service.cancel(run_id, caller)
        raise OpenAiError(504, "The answer took too long", "api_error", "timeout") from None
    finally:
        openai_chat_service.release_slot(caller.user_id)
    numbering = Numbering()
    text = numbering.convert(result.answer)
    sources = sources_of(numbering, result.citations)
    response: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text + sources_markdown(sources)},
                "finish_reason": "stop",
            }
        ],
        "sources": sources,
        "muffin": {"run_id": str(run_id), "conversation_id": str(conversation_id)},
    }
    if usage := _usage(result):
        response["usage"] = usage
    return JSONResponse(response)


async def _stream(
    request: Request,
    caller: RequestContext,
    body: ChatCompletionRequest,
    run_id: Any,
    completion_id: str,
    created: int,
    steps: bool,
) -> AsyncIterator[str]:
    def chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
        return _chunk(completion_id, body.model, created, delta, finish, **extra)

    numbering = Numbering()
    answer = AnswerStream(numbering)
    ended = False
    yield chunk({"role": "assistant", "content": ""})
    try:
        async for event in openai_chat_service.follow(run_id, request.is_disconnected):
            if event.kind == "delta":
                if text := answer.add(event.text, event.replace):
                    yield chunk({"content": text})
            elif event.kind == "activity" and steps:
                yield chunk({"reasoning_content": f"{event.text}\n"})
            elif event.kind == "end":
                ended = True
                break
        if not ended:
            await openai_chat_service.cancel(run_id, caller)
            return
        result = await openai_chat_service.final_of(run_id, caller)
        openai_chat_service.check_final(result)
    except TimeoutError:
        await openai_chat_service.cancel(run_id, caller)
        error = OpenAiError(504, "The answer took too long", "api_error", "timeout")
        yield f"data: {json.dumps(error.body())}\n\n"
        return
    except OpenAiError as error:
        yield f"data: {json.dumps(error.body())}\n\n"
        return
    except Exception:
        logger.exception(f"Following run {run_id} for the API failed")
        yield f"data: {json.dumps(OpenAiError(500, 'Internal error', 'api_error').body())}\n\n"
        return
    tail = answer.finish(result.answer)
    sources = sources_of(numbering, result.citations)
    if tail := tail + sources_markdown(sources):
        yield chunk({"content": tail})
    yield chunk({}, "stop", sources=sources)
    if body.stream_options and body.stream_options.include_usage:
        usage = _usage(result) or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        yield (
            "data: "
            + json.dumps(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": body.model,
                    "choices": [],
                    "usage": usage,
                }
            )
            + "\n\n"
        )
    yield "data: [DONE]\n\n"
