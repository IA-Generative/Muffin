import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.message import MessageRole
from app.models.run import RunStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.run_repository import RunRepository
from app.schemas.internal_run import (
    AccessibleCollectionOut,
    ConversationTitleUpdate,
    DocumentPageContentOut,
    DocumentSummaryOut,
    InternalRunOut,
    QaSearchResultOut,
    RunErrorUpdate,
    RunEventCreate,
    RunResultUpdate,
    RunStateUpdate,
    RunStatusUpdate,
    SearchRequest,
    SearchResultOut,
    SummarySearchResultOut,
)
from app.services.search_service import SearchService

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])

# How many prior messages get threaded into a new run's context (see InternalRunOut.history).
# Unbounded history would make analyze_query's prompt (and its latency) grow with every turn of
# a conversation - recent turns are what anaphora resolution ("elle", "ça") actually needs, not
# the entire thread.
_HISTORY_LIMIT = 8


def _to_out(run, history: list[dict[str, str]]) -> InternalRunOut:  # noqa: ANN001
    return InternalRunOut(
        id=run.id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        message_id=run.message_id,
        query=run.query,
        status=run.status,
        cancel_requested=run.cancel_requested,
        plan_version=run.plan_version,
        replan_count=run.replan_count,
        research_plan=run.research_plan,
        budget=run.budget,
        pending_human_action=run.pending_human_action,
        answer=run.answer,
        citations=run.citations,
        history=history,
        pinned_collection_ids=run.pinned_collection_ids,
    )


@router.get(
    "/runs/{run_id}", summary="Fetch a run's full state for the worker to resume/act on", response_model=InternalRunOut
)
async def get_run(run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> InternalRunOut:
    run = await RunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    # Oldest first, this run's own just-inserted user message excluded (see InternalRunOut.history)
    # - AgentService.run() appends it itself, right after this history, as the current question.
    messages = await ConversationRepository(db).list_messages(run.conversation_id)
    history = [
        {"role": message.role, "content": message.content}
        for message, _citations in messages
        if message.id != run.message_id
    ][-_HISTORY_LIMIT:]
    return _to_out(run, history)


@router.patch("/runs/{run_id}/status", summary="Report a run's status/current node/activity")
async def update_run_status(
    run_id: uuid.UUID, update: RunStatusUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.update_status(run, RunStatus(update.status), update.current_node, update.current_activity)
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/state", summary="Merge into a run's plan/budget/pending_human_action state")
async def update_run_state(
    run_id: uuid.UUID, update: RunStateUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.update_state(
        run, update.research_plan, update.budget, update.pending_human_action, update.plan_version, update.replan_count
    )
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/result", summary="Report a run's final answer and citations")
async def update_run_result(
    run_id: uuid.UUID, update: RunResultUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.set_result(run, update.answer, update.citations)
    # Persisted as a real Message, not just Run.answer, so GET /conversations/{id}/messages can
    # restore the full thread (§ conversation persistence) - Run stays about execution/status,
    # Message is the single source of truth for what the user actually sees in the chat history.
    await ConversationRepository(db).add_message(
        run.conversation_id, MessageRole.ASSISTANT, update.answer, run_id=run.id
    )
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/error", summary="Report a run failure")
async def update_run_error(
    run_id: uuid.UUID, update: RunErrorUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.set_error(run, update.error)
    await db.commit()
    return {"status": "ok"}


@router.post("/runs/{run_id}/events", summary="Record a structured progress event", status_code=status.HTTP_201_CREATED)
async def create_run_event(
    run_id: uuid.UUID, event: RunEventCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    if await repository.get_by_id(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.add_event(run_id, event.type, event.data, event.task_id)
    await db.commit()
    return {"status": "ok"}


@router.get(
    "/users/{user_id}/accessible-collections",
    summary="List the collections a user can reach - the only permission check the agent's VDB "
    "routing is allowed to trust (never the LLM, never the run payload)",
    response_model=list[AccessibleCollectionOut],
)
async def list_accessible_collections(
    user_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[AccessibleCollectionOut]:
    repository = CollectionRepository(db)
    collections = await repository.list_all_by_owner(user_id)
    document_counts = await repository.count_documents([collection.id for collection in collections])
    return [
        AccessibleCollectionOut(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            tags=[tag.tag for tag in collection.tags],
            document_count=document_counts.get(collection.id, 0),
        )
        for collection in collections
    ]


@router.get(
    "/users/{user_id}/collections/{collection_id}/documents",
    summary="List one collection's documents (id/name/status/summary) - the collection must be "
    "one this user owns, same permission barrier as accessible-collections",
    response_model=list[DocumentSummaryOut],
)
async def list_collection_documents(
    user_id: str, collection_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[DocumentSummaryOut]:
    if await CollectionRepository(db).get(collection_id, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    documents = await DocumentRepository(db).list_by_collection(collection_id)
    return [
        DocumentSummaryOut(id=document.id, name=document.name, status=document.status, summary=document.summary)
        for document in documents
    ]


@router.get(
    "/users/{user_id}/documents/{document_id}/pages/{page_number}",
    summary="Fetch one page's text and a short-lived screenshot URL - the document's collection "
    "must be one this user owns, same permission barrier as accessible-collections",
    response_model=DocumentPageContentOut,
)
async def get_document_page(
    user_id: str, document_id: uuid.UUID, page_number: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> DocumentPageContentOut:
    documents = DocumentRepository(db)
    document = await documents.get_with_collection(document_id)
    if document is None or document.collection.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    page = await documents.get_page(document_id, page_number)
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
    return DocumentPageContentOut(
        page_number=page.page_number,
        content=page.content,
        screenshot_url=storage.get_presigned_url(page.screenshot) if page.screenshot else None,
    )


@router.patch(
    "/conversations/{conversation_id}/title",
    summary="Rewrite a conversation's title from its first run's query+answer - a one-time, "
    "idempotent event (no-op once title_generated is set) so a later run in the same "
    "conversation never overwrites a title the first one already generated",
)
async def update_conversation_title(
    conversation_id: uuid.UUID, body: ConversationTitleUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = ConversationRepository(db)
    conversation = await repository.get_by_id(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if not conversation.title_generated:
        await repository.set_generated_title(conversation, body.title)
        await db.commit()
    return {"status": "ok"}


@router.post(
    "/search",
    summary="Vector search (Qdrant) over the chunks of the given collections",
    response_model=list[SearchResultOut],
)
async def search(body: SearchRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> list[SearchResultOut]:
    rows = await SearchService(db).search(body.collection_ids, body.query, body.limit)
    return [
        SearchResultOut(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=document_name,
            collection_id=collection_id,
            text=chunk.text,
            rank=rank,
            page_number=(chunk.extras or {}).get("page_start"),
        )
        for chunk, document_name, collection_id, rank in rows
    ]


@router.post(
    "/qa-search",
    summary="Vector search (Qdrant) over the QA pairs of the given collections - the research "
    "agent's QA-first retrieval tier, tried before falling back to summaries then chunk search",
    response_model=list[QaSearchResultOut],
)
async def qa_search(body: SearchRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> list[QaSearchResultOut]:
    rows = await SearchService(db).search_qa(body.collection_ids, body.query, body.limit)
    return [
        QaSearchResultOut(
            qa_pair_id=qa_pair.id,
            collection_id=collection_id,
            question=qa_pair.question,
            answer=qa_pair.answer,
            score=score,
        )
        for qa_pair, collection_id, score in rows
    ]


@router.post(
    "/summary-search",
    summary="Vector search (Qdrant) over the document summaries of the given collections - the "
    "research agent's tier-2 retrieval, tried after a QA miss and before a full chunk search",
    response_model=list[SummarySearchResultOut],
)
async def summary_search(
    body: SearchRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[SummarySearchResultOut]:
    rows = await SearchService(db).search_summaries(body.collection_ids, body.query, body.limit)
    return [
        SummarySearchResultOut(
            document_id=document.id,
            collection_id=document.collection_id,
            name=document.name,
            summary=document.summary,
            score=score,
        )
        for document, score in rows
    ]
