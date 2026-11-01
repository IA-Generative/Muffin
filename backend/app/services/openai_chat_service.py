"""The OpenAI-compatible API (#513): a "model" is a scope of search, and a chat completion is a run of Muffin's agent.

The agent writes the answer, cited and checked, from the collections the key's owner may read - nothing here widens
that: the run is the owner's, made the way the chat makes it (RunService.create_run). What this does is turn the
request into a run, follow the run, and turn what it writes into what an OpenAI client reads: the text with numbered
citations, a list of sources, the usage."""

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph.services.citations import replace_markers
from app.config import OpenAiApiSettings, RunSettings
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.message import MessageRole
from app.models.run import RunStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.run_repository import RunRepository
from app.schemas.openai_api import ChatCompletionRequest, ChatMessage, ModelList, ModelOut
from app.schemas.run import RunCreate
from app.services import run_stream
from app.services.guardrail_service import GuardrailService
from app.services.mcp_search_service import document_url
from app.services.run_service import ConversationNotFoundError, RunNotFoundError, RunService

_settings = OpenAiApiSettings()
_run_settings = RunSettings()

SOURCE = "api"
DEFAULT_MODEL = "muffin"
_COLLECTION_MODEL = "muffin:collection:"

# What the request holds that would change what the answer is, and that the agent cannot do: refused rather than
# ignored without a word. (temperature and max_tokens are accepted and not used: the agent chooses its own.)
_UNSUPPORTED = ("tools", "functions", "tool_choice", "function_call", "response_format", "logprobs", "top_logprobs")

# The answers in the making through the API for each user on this pod.
_in_the_making: Counter[str] = Counter()

# A bracket of citations that is not closed yet is held back, up to this long: past it, it was not one.
_MARKER_MAX_CHARS = 120
_EXCERPT_CHARS = 300


class OpenAiError(Exception):
    """An error as OpenAI's API tells it: `{"error": {"message", "type", "code"}}`."""

    def __init__(self, status_code: int, message: str, error_type: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code

    def body(self) -> dict[str, Any]:
        return {"error": {"message": self.message, "type": self.error_type, "code": self.code, "param": None}}


def invalid_request(message: str, code: str | None = None) -> OpenAiError:
    return OpenAiError(400, message, "invalid_request_error", code)


@dataclass
class Final:
    """What a run came to: read from the database, which is what it really is whatever the stream said."""

    status: str
    answer: str
    citations: list[dict[str, Any]]
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None
    conversation_id: uuid.UUID | None


@dataclass
class Event:
    """What happens while a run goes on: `activity` (what the agent is doing), `delta` (more of the answer, or all of
    it again when `replace`), and `end` (the run is over: the status)."""

    kind: str
    text: str = ""
    replace: bool = False


@dataclass
class Numbering:
    """The citations of an answer as the numbers a client reads, in the order the answer cites them."""

    numbers: dict[str, int] = field(default_factory=dict)

    def render(self, ids: list[str]) -> str:
        out = []
        for evidence_id in ids:
            number = self.numbers.setdefault(evidence_id, len(self.numbers) + 1)
            out.append(f"[{number}]")
        return "".join(out)

    def convert(self, text: str) -> str:
        return replace_markers(text, self.render)


class AnswerStream:
    """The answer as it is written, turned into text for a client, piece by piece. A bracket of citations that is cut
    in two between two pieces is held back until it is whole, so that the client never sees a marker half done."""

    def __init__(self, numbering: Numbering) -> None:
        self.numbering = numbering
        self.raw = ""
        self._sent = 0  # how much of `raw` has been turned into text for the client

    def add(self, text: str, replace: bool) -> str:
        # A replacement that changes what the client was already given cannot take it back: what is left of it is
        # sent, and the end of the run settles the rest.
        self.raw = text if replace else self.raw + text
        return self._flush(self._safe_end(self.raw))

    def finish(self, answer: str) -> str:
        """The rest of the final answer. If what was streamed is not its beginning, nothing more is added to it."""
        if not answer.startswith(self.raw[: self._sent]):
            return ""
        self.raw = answer
        return self._flush(len(answer))

    def _safe_end(self, text: str) -> int:
        opening = text.rfind("[")
        if opening != -1 and "]" not in text[opening:] and len(text) - opening <= _MARKER_MAX_CHARS:
            return opening
        return len(text)

    def _flush(self, end: int) -> str:
        if end <= self._sent:
            return ""
        piece = self.raw[self._sent : end]
        self._sent = end
        return self.numbering.convert(piece)


def sources_of(numbering: Numbering, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sources the answer cites, by the numbers it cites them with."""
    by_id = {str(citation.get("evidence_id")): citation for citation in citations}
    sources = []
    for evidence_id, number in numbering.numbers.items():
        citation = by_id.get(evidence_id, {})
        collection_id, document_id = citation.get("vdb_id"), citation.get("document_id")
        url = citation.get("url")
        if url is None and collection_id and document_id:
            try:
                url = document_url(uuid.UUID(str(collection_id)), uuid.UUID(str(document_id)))
            except ValueError:
                url = None
        excerpt = citation.get("quote") or citation.get("content") or ""
        sources.append(
            {
                "index": number,
                "id": evidence_id,
                "name": citation.get("source"),
                "page": citation.get("page_number"),
                "url": url,
                "excerpt": excerpt[:_EXCERPT_CHARS] or None,
            }
        )
    return sources


def sources_markdown(sources: list[dict[str, Any]]) -> str:
    """The list of sources at the end of the answer, for the clients that show only text."""
    if not sources:
        return ""
    lines = []
    for source in sources:
        label = source["name"] or "Source"
        page = f", p. {source['page']}" if source["page"] else ""
        link = f" - {source['url']}" if source["url"] else ""
        lines.append(f"[{source['index']}] {label}{page}{link}")
    return "\n\n**Sources**\n\n" + "\n\n".join(lines)


def _text_of(message: ChatMessage) -> str:
    content = message.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if part.get("type") != "text":
            raise invalid_request(
                f"Content of type '{part.get('type')}' is not supported: Muffin reads text only", "unsupported_content"
            )
        parts.append(str(part.get("text", "")))
    return "\n".join(parts)


class OpenAiChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.conversations = ConversationRepository(db)

    # --- models ---

    async def list_models(self, user: RequestContext) -> ModelList:
        """`muffin` (every collection the owner reads) and, besides, each top-level collection they read."""
        now = int(time.time())
        data = [ModelOut(id=DEFAULT_MODEL, created=now, name="Muffin")]
        found, _total = await self.collections.list_accessible(
            user.user_id,
            user.groups,
            limit=_settings.OPENAI_API_MAX_LISTED_COLLECTIONS,
            offset=0,
            exclude_temporary=True,
            roots_only=True,
        )
        for collection in found:
            data.append(
                ModelOut(
                    id=f"{_COLLECTION_MODEL}{collection.id}",
                    created=int(collection.created_at.timestamp()),
                    name=f"Muffin - {collection.name}",
                )
            )
        return ModelList(data=data)

    async def get_model(self, user: RequestContext, model: str) -> ModelOut:
        scope = await self.resolve_model(user, model)
        if scope is None:
            return ModelOut(id=DEFAULT_MODEL, created=int(time.time()), name="Muffin")
        collection = await self.collections.get_by_id(scope)
        return ModelOut(id=model, created=int(collection.created_at.timestamp()), name=f"Muffin - {collection.name}")

    async def resolve_model(self, user: RequestContext, model: str) -> uuid.UUID | None:
        """The collection a model is limited to, None for `muffin`. A collection the owner cannot read does not exist
        for them."""
        if model == DEFAULT_MODEL:
            return None
        not_found = OpenAiError(404, f"The model '{model}' does not exist", "invalid_request_error", "model_not_found")
        if not model.startswith(_COLLECTION_MODEL):
            raise not_found
        try:
            collection_id = uuid.UUID(model.removeprefix(_COLLECTION_MODEL))
        except ValueError:
            raise not_found from None
        if not await self.collections.filter_accessible_ids([collection_id], user.user_id, user.groups):
            raise not_found
        return collection_id

    # --- a chat completion ---

    def check_request(self, request: ChatCompletionRequest) -> tuple[list[ChatMessage], str]:
        """The earlier messages and the question, or the reason the request cannot be answered."""
        for name in _UNSUPPORTED:
            value = getattr(request, name)
            if value not in (None, False, [], {}):
                raise invalid_request(f"'{name}' is not supported by Muffin", "unsupported_parameter")
        if request.n not in (None, 1):
            raise invalid_request("'n' is not supported by Muffin: only one answer is written", "unsupported_parameter")
        # Muffin has its own instructions for the agent: the ones of the client are not part of the conversation.
        messages = [message for message in request.messages if message.role in ("user", "assistant")]
        if len(request.messages) > _settings.OPENAI_API_MAX_MESSAGES:
            raise invalid_request(f"A request holds {_settings.OPENAI_API_MAX_MESSAGES} messages at most")
        if not messages or messages[-1].role != "user":
            raise invalid_request("The last message must be the user's question", "invalid_messages")
        for message in messages:
            if len(_text_of(message)) > _settings.OPENAI_API_MAX_MESSAGE_CHARS:
                raise invalid_request(
                    f"A message may hold {_settings.OPENAI_API_MAX_MESSAGE_CHARS} characters at most",
                    "message_too_long",
                )
        question = _text_of(messages[-1]).strip()
        if not question:
            raise invalid_request("The question is empty", "invalid_messages")
        return messages[:-1], question

    async def start(
        self,
        user: RequestContext,
        request: ChatCompletionRequest,
        conversation_header: str | None,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Makes the run for the question. Returns the id of the run and of its conversation."""
        history, question = self.check_request(request)
        scope = await self.resolve_model(user, request.model)
        asked = conversation_header or (request.muffin.conversation_id if request.muffin else None)
        if asked:
            try:
                conversation = await self.conversations.get(uuid.UUID(asked), user.user_id)
            except ValueError:
                conversation = None
            if conversation is None:
                raise OpenAiError(404, "Conversation not found", "invalid_request_error", "conversation_not_found")
        else:
            await self.conversations.purge_from_source(
                SOURCE, datetime.now(UTC) - timedelta(days=_settings.OPENAI_API_RETENTION_DAYS)
            )
            conversation = await self.conversations.create(user.user_id, title=question[:80], source=SOURCE)
            # The history the client holds is the conversation the agent reads.
            # Dated one millisecond apart and before the question: the database dates what a transaction writes with the
            # time the transaction began, which would leave the order of the messages to chance.
            began = await self.db.scalar(select(func.now()))
            stored = []
            for position, message in enumerate(history, start=-len(history)):
                role = MessageRole.USER if message.role == "user" else MessageRole.ASSISTANT
                stored.append(
                    await self.conversations.add_message(
                        conversation.id, role, _text_of(message), created_at=began + timedelta(milliseconds=position)
                    )
                )
            # No run checks these: the guardrails that run without a model do (#516).
            await GuardrailService(self.db).screen_history(user, stored)
        try:
            run = await RunService(self.db).create_run(
                user,
                RunCreate(
                    query=question,
                    conversation_id=conversation.id,
                    collection_ids=[scope] if scope else None,
                    interactive=False,
                ),
                # A model of one collection answers from it alone: the planner may not go on to the others.
                scope_locked=scope is not None,
            )
        except ConversationNotFoundError:
            raise OpenAiError(
                404, "Conversation not found", "invalid_request_error", "conversation_not_found"
            ) from None
        return run.id, conversation.id


# --- following a run ---


async def _status_of(run_id: uuid.UUID) -> str | None:
    async with async_session_factory() as db:
        run = await RunRepository(db).get_by_id(run_id)
        return run.status.value if run is not None else None


async def cancel(run_id: uuid.UUID, user: RequestContext) -> None:
    try:
        async with async_session_factory() as db:
            await RunService(db).cancel_run(run_id, user)
    except Exception:
        logger.warning(f"Could not cancel run {run_id}", exc_info=True)


def acquire_slot(user_id: str) -> None:
    if _in_the_making[user_id] >= _settings.OPENAI_API_RUNS_PER_USER:
        raise OpenAiError(
            429, "Too many answers in the making: wait for one to end", "rate_limit_error", "too_many_runs"
        )
    _in_the_making[user_id] += 1


def release_slot(user_id: str) -> None:
    _in_the_making[user_id] -= 1
    if _in_the_making[user_id] <= 0:
        del _in_the_making[user_id]


async def follow(run_id: uuid.UUID, is_disconnected: Any) -> AsyncIterator[Event]:
    """What the run does, until it is over - the stream of the run, with the database as the judge of its end. Raises
    TimeoutError when the answer takes too long; the caller cancels the run."""
    ping = _run_settings.RUN_STREAM_PING_SECONDS
    cursor = "0-0"
    deadline = time.monotonic() + _settings.OPENAI_API_TIMEOUT_SECONDS
    shown_activity = ""
    while not await is_disconnected():
        if time.monotonic() > deadline:
            raise TimeoutError
        try:
            entries = await run_stream.read(run_id, cursor, min(ping, 2) * 1000)
        except Exception:
            # No stream (Redis down, expired): the run itself is looked at instead, a little later.
            logger.warning(f"Could not read the stream of run {run_id}", exc_info=True)
            await asyncio.sleep(1)
            entries = []
        for entry in entries:
            cursor = entry.id
            if entry.kind == run_stream.DELTA:
                yield Event("delta", entry.payload.get("text", ""), bool(entry.payload.get("replace")))
            elif entry.kind == run_stream.STATUS:
                activity = entry.payload.get("current_activity") or ""
                if activity and activity != shown_activity:
                    shown_activity = activity
                    yield Event("activity", activity)
                if entry.payload.get("status") in run_stream.ENDING_STATUSES:
                    yield Event("end", entry.payload["status"])
                    return
        if not entries:
            current = await _status_of(run_id)
            if current in run_stream.ENDING_STATUSES:
                yield Event("end", current)
                return


async def final_of(run_id: uuid.UUID, user: RequestContext) -> Final:
    async with async_session_factory() as db:
        try:
            run = await RunService(db).get_run(run_id, user)
        except RunNotFoundError:
            raise OpenAiError(500, "The answer was lost", "api_error", "run_lost") from None
        message = await ConversationRepository(db).get_assistant_message_by_run_id(run_id)
    return Final(
        status=run.status,
        answer=run.answer or "",
        citations=run.citations or [],
        prompt_tokens=message.prompt_tokens if message else None,
        completion_tokens=message.completion_tokens if message else None,
        error=run.error,
        conversation_id=run.conversation_id,
    )


def check_final(result: Final) -> None:
    """Turns a run that did not give an answer into an error: what went wrong inside is not told to the client."""
    if result.status == RunStatus.COMPLETED.value and result.answer:
        return
    if result.status == RunStatus.CANCELLED.value:
        raise OpenAiError(499, "The request was cancelled", "api_error", "cancelled")
    logger.warning(f"A run of the API ended {result.status}: {result.error}")
    raise OpenAiError(502, "Muffin could not write an answer", "api_error", "run_failed")
