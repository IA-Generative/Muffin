import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RunSettings
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory, get_db
from app.repositories.run_repository import RunRepository
from app.schemas.document import DocumentOut
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.schemas.question import InvalidAnswersError
from app.schemas.run import RunCreate, RunEventOut, RunOut, RunResumeRequest
from app.services import run_stream
from app.services.collection_service import CollectionNotEditableError, CollectionNotFoundError
from app.services.creation_proposal_service import CreationProposalService, NoPendingCreationError
from app.services.image_attachment_service import AttachmentError
from app.services.run_service import (
    ConversationNotFoundError,
    QuestionsNotAnswerableError,
    RunHasNoAnswerError,
    RunNotFoundError,
    RunNotWaitingError,
    RunService,
)

router = APIRouter(tags=["Runs"])

_run_settings = RunSettings()
# The streams held open by each user on this pod (#510). Each one is a request kept for the length of an answer.
_open_streams: Counter[str] = Counter()
_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    # nginx would hold the pieces back until a buffer is full, which is the opposite of a stream.
    "X-Accel-Buffering": "no",
}


def get_run_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RunService:
    return RunService(db)


def get_creation_service(db: Annotated[AsyncSession, Depends(get_db)]) -> CreationProposalService:
    return CreationProposalService(db)


ServiceDep = Annotated[RunService, Depends(get_run_service)]
CreationServiceDep = Annotated[CreationProposalService, Depends(get_creation_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.post(
    "/runs",
    summary="Start a research agent run (returns immediately, doesn't wait for completion)",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunOut,
)
async def create_run(body: RunCreate, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.create_run(user, body)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    except QuestionsNotAnswerableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="There are no questions waiting for an answer here"
        ) from error
    except InvalidAnswersError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    except AttachmentError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message}) from error


@router.get("/runs/{run_id}", summary="Get a run's current status/result", response_model=RunOut)
async def get_run(run_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.get_run(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


def _sse(kind: str, payload: dict[str, Any], entry_id: str | None = None) -> str:
    head = f"id: {entry_id}\n" if entry_id else ""
    return f"{head}event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _run_status(run_id: uuid.UUID) -> str | None:
    """The status in the database, which is what the run really is whatever the stream says (or no longer says)."""
    async with async_session_factory() as db:
        run = await RunRepository(db).get_by_id(run_id)
        return run.status.value if run is not None else None


async def _follow_run(
    request: Request, run_id: uuid.UUID, user_id: str, cursor: str, status_now: str
) -> AsyncIterator[str]:
    _open_streams[user_id] += 1
    ping = _run_settings.RUN_STREAM_PING_SECONDS
    try:
        yield "retry: 3000\n\n"
        # A run that is already over has nothing to wait for: what is left of its stream is read at once.
        block_ms = 0 if status_now in run_stream.ENDING_STATUSES else ping * 1000
        while not await request.is_disconnected():
            try:
                entries = await run_stream.read(run_id, cursor, block_ms)
            except Exception:
                logger.warning(f"Could not read the stream of run {run_id}", exc_info=True)
                yield _sse("unavailable", {})
                return
            for entry in entries:
                cursor = entry.id
                yield _sse(entry.kind, entry.payload, entry.id)
                if entry.kind == run_stream.STATUS and entry.payload.get("status") in run_stream.ENDING_STATUSES:
                    return
            if entries:
                block_ms = ping * 1000
                continue
            # Nothing came: either the run is quiet, or it ended without a word (a pod that went down, a stream that
            # expired) - the database tells which.
            current = await _run_status(run_id)
            if current in run_stream.ENDING_STATUSES:
                yield _sse(run_stream.STATUS, {"status": current})
                return
            block_ms = ping * 1000
            yield _sse(run_stream.PING, {})
    finally:
        _open_streams[user_id] -= 1
        if _open_streams[user_id] <= 0:
            del _open_streams[user_id]


@router.get(
    "/runs/{run_id}/stream",
    summary="Follow a run live (Server-Sent Events): its steps, the answer as it is written, then its status. "
    "Resumes after `Last-Event-ID`. The run itself (GET /runs/{id}) stays the source of truth.",
    response_class=StreamingResponse,
)
async def stream_run(
    run_id: uuid.UUID,
    request: Request,
    user: UserDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    # Not through the request's own session: it would be held, with its connection, for as long as the stream is open.
    async with async_session_factory() as db:
        try:
            run = await RunService(db).get_run(run_id, user)
        except RunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    if _open_streams[user.user_id] >= _run_settings.RUN_STREAMS_PER_USER:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many streams open")
    return StreamingResponse(
        _follow_run(request, run_id, user.user_id, last_event_id or "0-0", run.status),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.get(
    "/runs/{run_id}/events",
    summary="List a run's structured progress events, oldest first (poll with `since` for incremental updates)",
    response_model=list[RunEventOut],
)
async def list_run_events(
    run_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    since: uuid.UUID | None = None,
) -> list[RunEventOut]:
    # Not actually paginated (§ a run's own event log is a bounded, append-only trace, not a
    # list to page through) - `page_size` used to be accepted here via the shared
    # PaginationParams, whose page_size<=100 cap made the frontend's ?page_size=200 always fail
    # validation (422), silently emptying the execution detail panel for every run.
    try:
        return await service.list_events(run_id, user, since)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


@router.post(
    "/runs/{run_id}/resume",
    summary="Answer a run's pending clarification question and continue it (only valid while "
    "status is waiting_for_user)",
    response_model=RunOut,
)
async def resume_run(run_id: uuid.UUID, body: RunResumeRequest, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.resume_run(run_id, user, body.answer)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    except RunNotWaitingError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is not waiting for a clarification",
        ) from error


@router.post(
    "/runs/{run_id}/feedback",
    summary="Leave a thumbs up/down (and optionally reasons/a comment) on a run's answer - the "
    "only identifier an external caller (chat, MCP, A2A) needs to have in hand is the run_id",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackOut,
)
async def submit_feedback(run_id: uuid.UUID, body: FeedbackCreate, user: UserDep, service: ServiceDep) -> FeedbackOut:
    try:
        return await service.submit_feedback(run_id, user, body)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    except RunHasNoAnswerError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run has no answer to give feedback on yet",
        ) from error


@router.get(
    "/runs/{run_id}/feedback",
    summary="Get the current user's feedback on a run's answer - used to pre-fill the modal when editing",
    response_model=FeedbackOut | None,
)
async def get_feedback(run_id: uuid.UUID, user: UserDep, service: ServiceDep) -> FeedbackOut | None:
    try:
        return await service.get_feedback(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


@router.post(
    "/runs/{run_id}/cancel",
    summary="Request cancellation of a run (cooperative - nodes check this at key points, it isn't instant)",
    response_model=RunOut,
)
async def cancel_run(run_id: uuid.UUID, user: UserDep, service: ServiceDep) -> RunOut:
    try:
        return await service.cancel_run(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error


@router.post(
    "/runs/{run_id}/creation/validate",
    summary="Create the Markdown document the agent proposed in this run's answer",
    response_model=DocumentOut,
)
async def validate_creation(run_id: uuid.UUID, user: UserDep, service: CreationServiceDep) -> DocumentOut:
    try:
        return await service.validate(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    except NoPendingCreationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_pending_creation", "message": "Ce document a déjà été créé ou refusé."},
        ) from error
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except CollectionNotEditableError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the collection's owner or an administrator can edit it"
        ) from error


@router.post(
    "/runs/{run_id}/creation/refuse",
    summary="Decline the document the agent proposed: nothing is created",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def refuse_creation(run_id: uuid.UUID, user: UserDep, service: CreationServiceDep) -> None:
    try:
        await service.refuse(run_id, user)
    except RunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from error
    except NoPendingCreationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_pending_creation", "message": "Ce document a déjà été créé ou refusé."},
        ) from error
