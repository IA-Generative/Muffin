"""Muffin's assistants as A2A agents (#a2a): an agent card and a `message/send` endpoint per assistant exposed this
way, for an external agent to consult the way the chat does - cited, checked, from its own collections.

Same two ways in as the OpenAI-compatible API, for two different kinds of caller:
- **A personal API key** (`Authorization: Bearer sk-muffin-…`, scope `chat`): the call runs as the key's owner, and
  the assistant must be both usable by them and exposed as an agent (`AssistantService.for_a2a`) - this opens
  nothing that using the assistant in the chat did not already.
- **The assistant's own dedicated token** (`Authorization: Bearer a2a-muffin-…`): for an external agent with no
  Muffin account at all, the call runs with its owner's own rights (there being no one else it could sensibly run
  as) - see `AssistantService.authenticate_a2a_token`.

Everything else - the run, its citations, its rights - is exactly `RunService.create_run` with `assistant_id` set,
the same code the chat and the OpenAI-compatible API use."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KeycloakSettings, OpenAiApiSettings
from app.core.api_keys import PREFIX as API_KEY_PREFIX
from app.core.security.factory import RequestContext
from app.db import get_db
from app.models.api_key import SCOPE_CHAT
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.run import RunCreate
from app.services import openai_chat_service
from app.services.api_key_service import ApiKeyRateLimitedError, ApiKeyService, InvalidApiKeyError
from app.services.assistant_service import A2A_TOKEN_PREFIX, AssistantNotFoundError, AssistantService
from app.services.openai_chat_service import OpenAiError
from app.services.run_service import RunService

router = APIRouter(tags=["A2A"])

_settings = OpenAiApiSettings()
_keycloak_settings = KeycloakSettings()
_SOURCE = "a2a"
_NOT_FOUND = "Assistant not found"


async def a2a_caller(
    assistant_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> RequestContext:
    """Who a call stands for - never said which of the two ways in was wrong, nor whether a token merely had the
    right shape: an assistant not exposed this way, and a token that is not one, look the same."""
    not_found = HTTPException(404, _NOT_FOUND)
    if not authorization or not authorization.startswith("Bearer "):
        raise not_found
    token = authorization.removeprefix("Bearer ")
    if token.startswith(A2A_TOKEN_PREFIX):
        user = await AssistantService(db).authenticate_a2a_token(assistant_id, token)
        if user is None:
            raise not_found
        return user
    if token.startswith(API_KEY_PREFIX):
        try:
            return await ApiKeyService(db).authenticate(token, SCOPE_CHAT)
        except ApiKeyRateLimitedError:
            raise HTTPException(429, "Too many requests: slow down") from None
        except InvalidApiKeyError:
            raise HTTPException(401, "Incorrect API key provided") from None
    raise not_found


CallerDep = Annotated[RequestContext, Depends(a2a_caller)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def _question_from(params: dict[str, Any]) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") if isinstance(message, dict) else None
    if not isinstance(parts, list):
        return ""
    return "\n".join(str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("kind") == "text")


def _rpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _rpc_result(request_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


@router.get("/a2a/assistants/{assistant_id}/.well-known/agent-card.json", summary="An assistant's A2A agent card")
async def agent_card(assistant_id: uuid.UUID, user: CallerDep, db: DbDep) -> dict[str, Any]:
    try:
        resolved = await AssistantService(db).for_a2a(user, assistant_id)
    except AssistantNotFoundError:
        raise HTTPException(404, _NOT_FOUND) from None
    base = f"{_keycloak_settings.BACKEND_PUBLIC_URL}/api/a2a/assistants/{assistant_id}"
    return {
        "protocolVersion": "0.2.9",
        "name": resolved.name,
        "description": resolved.instructions[:500] or f"L'assistant « {resolved.name} » de Muffin.",
        "url": base,
        "version": str(resolved.version),
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "search",
                "name": resolved.name,
                "description": resolved.instructions[:500] or "Répond en cherchant dans ses propres documents.",
                "tags": ["muffin", "search"],
            }
        ],
    }


@router.post("/a2a/assistants/{assistant_id}", summary="JSON-RPC endpoint of an assistant's A2A agent")
async def a2a_endpoint(
    assistant_id: uuid.UUID, body: dict[str, Any], request: Request, user: CallerDep, db: DbDep
) -> Any:
    request_id = body.get("id")
    if body.get("method") != "message/send":
        return _rpc_error(request_id, -32601, "Method not found: only message/send is supported")
    question = _question_from(body.get("params") or {}).strip()
    if not question:
        return _rpc_error(request_id, -32602, "Invalid params: message has no text part")
    try:
        answer = await _run_and_answer(user, assistant_id, question, request, db)
    except AssistantNotFoundError:
        return _rpc_error(request_id, -32001, "Assistant not found")
    except OpenAiError as error:
        return _rpc_error(request_id, -32000, error.message)
    return _rpc_result(
        request_id,
        {
            "role": "agent",
            "parts": [{"kind": "text", "text": answer}],
            "messageId": str(uuid.uuid4()),
            "kind": "message",
        },
    )


async def _run_and_answer(
    user: RequestContext, assistant_id: uuid.UUID, question: str, request: Request, db: AsyncSession
) -> str:
    """One question, answered the way the chat with this assistant would (its own collections, its own
    instructions) - cited and checked, read back as plain text: an A2A message has no sources panel to put them
    in, so they end as the chat's own trailing `**Sources**` block (see `sources_markdown`)."""
    await AssistantService(db).for_a2a(user, assistant_id)
    conversations = ConversationRepository(db)
    cutoff = datetime.now(UTC) - timedelta(days=_settings.OPENAI_API_RETENTION_DAYS)
    await conversations.purge_from_source(_SOURCE, cutoff)
    conversation = await conversations.create(user.user_id, title=question[:80], source=_SOURCE)
    openai_chat_service.acquire_slot(user.user_id)
    try:
        run = await RunService(db).create_run(
            user,
            RunCreate(query=question, conversation_id=conversation.id, assistant_id=assistant_id, interactive=False),
            scope_locked=True,
        )
        try:
            async for event in openai_chat_service.follow(run.id, request.is_disconnected):
                if event.kind == "end":
                    break
            else:
                await openai_chat_service.cancel(run.id, user)
                raise OpenAiError(499, "The caller closed the request", "api_error", "client_closed")
            result = await openai_chat_service.final_of(run.id, user)
            openai_chat_service.check_final(result)
        except TimeoutError:
            await openai_chat_service.cancel(run.id, user)
            raise OpenAiError(504, "The answer took too long", "api_error", "timeout") from None
    finally:
        openai_chat_service.release_slot(user.user_id)
    numbering = openai_chat_service.Numbering()
    text = numbering.convert(result.answer)
    sources = openai_chat_service.sources_of(numbering, result.citations)
    return text + openai_chat_service.sources_markdown(sources)
