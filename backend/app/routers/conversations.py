import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.conversation import ConversationOut, ConversationUpdate, MessageOut
from app.schemas.discussion_feedback import (
    DiscussionFeedbackCreate,
    DiscussionFeedbackOut,
)
from app.schemas.discussion_score import DiscussionScoreOut
from app.schemas.document import DocumentOut
from app.schemas.pagination import Page, PaginationParams
from app.schemas.run import RunOut
from app.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
)
from app.services.document_upload_service import (
    DocumentNotFoundError,
    DocumentUploadService,
)
from app.services.run_service import (
    ConversationNotFoundError as RunConversationNotFoundError,
)
from app.services.run_service import (
    RunService,
)

router = APIRouter(tags=["Conversations"])


def get_conversation_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationService:
    return ConversationService(db)


def get_run_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RunService:
    return RunService(db)


def get_document_upload_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentUploadService:
    return DocumentUploadService(db)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
DocumentUploadServiceDep = Annotated[DocumentUploadService, Depends(get_document_upload_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/conversations",
    summary="List the user's conversations, most recently active first",
    response_model=Page[ConversationOut],
)
async def list_conversations(
    user: UserDep,
    service: ConversationServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[ConversationOut]:
    return await service.list_conversations(user, pagination)


@router.get(
    "/conversations/{conversation_id}",
    summary="Get a single conversation - used by the frontend to pick up an auto-generated title "
    "after a run completes without waiting for a full page reload",
    response_model=ConversationOut,
)
async def get_conversation(
    conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep
) -> ConversationOut:
    try:
        return await service.get_conversation(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="List a conversation's messages, oldest first - used to restore a chat thread",
    response_model=list[MessageOut],
)
async def list_conversation_messages(
    conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep
) -> list[MessageOut]:
    try:
        return await service.list_messages(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.get(
    "/conversations/{conversation_id}/active-runs",
    summary="List non-terminal runs for a conversation - used after a page refresh to resume polling",
    response_model=list[RunOut],
)
async def list_active_runs(conversation_id: uuid.UUID, user: UserDep, service: RunServiceDep) -> list[RunOut]:
    try:
        return await service.list_active_runs(conversation_id, user)
    except RunConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.post(
    "/conversations/{conversation_id}/discussion-score",
    summary="Trigger a discussion-quality judgment for this conversation (runs asynchronously in "
    "worker/evaluation - see #31)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_discussion_score(
    conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep
) -> dict[str, str]:
    try:
        celery_task_id = await service.trigger_discussion_score(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return {"celery_task_id": celery_task_id}


@router.get(
    "/conversations/{conversation_id}/discussion-scores",
    summary="List this conversation's discussion-quality judgments, most recent first (see #31)",
    response_model=list[DiscussionScoreOut],
)
async def list_discussion_scores(
    conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep
) -> list[DiscussionScoreOut]:
    try:
        return await service.list_discussion_scores(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.post(
    "/conversations/{conversation_id}/discussion-feedback",
    summary="Submit or update the current user's holistic judgment of this conversation - the "
    "human counterpart to the LLM-generated discussion score",
    response_model=DiscussionFeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_discussion_feedback(
    conversation_id: uuid.UUID,
    user: UserDep,
    service: ConversationServiceDep,
    body: DiscussionFeedbackCreate,
) -> DiscussionFeedbackOut:
    try:
        return await service.submit_discussion_feedback(
            conversation_id,
            user,
            rating=body.rating,
            coherent=body.coherent,
            context_usage_score=body.context_usage_score,
            comment=body.comment,
        )
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.get(
    "/conversations/{conversation_id}/discussion-feedback",
    summary="List this conversation's human discussion feedback, most recent first",
    response_model=list[DiscussionFeedbackOut],
)
async def list_discussion_feedback(
    conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep
) -> list[DiscussionFeedbackOut]:
    try:
        return await service.list_discussion_feedback(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.patch(
    "/conversations/{conversation_id}",
    summary="Rename a conversation - locks it against the auto-generated title ever overwriting it",
    response_model=ConversationOut,
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: UserDep,
    service: ConversationServiceDep,
) -> ConversationOut:
    try:
        return await service.rename_conversation(conversation_id, user, body.title)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete a conversation and everything in it (messages, runs, run events)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(conversation_id: uuid.UUID, user: UserDep, service: ConversationServiceDep) -> None:
    try:
        await service.delete_conversation(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error


@router.post(
    "/conversations/{conversation_id}/documents/file",
    summary="Upload a file directly into a conversation (§ conv-files) - indexed and searchable "
    "by the agent in this conversation's subsequent messages, without an explicit collection",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_conversation_file(
    conversation_id: uuid.UUID,
    file: UploadFile,
    user: UserDep,
    conversations: ConversationServiceDep,
    documents: DocumentUploadServiceDep,
) -> DocumentOut:
    try:
        await conversations.get_conversation(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    content = await file.read()
    return await documents.create_conversation_file_document(
        conversation_id, user, file.filename, content, file.content_type or "application/octet-stream"
    )


@router.get(
    "/conversations/{conversation_id}/documents",
    summary="List files attached to a conversation - empty if none have been uploaded yet",
    response_model=list[DocumentOut],
)
async def list_conversation_documents(
    conversation_id: uuid.UUID,
    user: UserDep,
    conversations: ConversationServiceDep,
    documents: DocumentUploadServiceDep,
) -> list[DocumentOut]:
    try:
        await conversations.get_conversation(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return await documents.list_conversation_documents(conversation_id, user)


@router.delete(
    "/conversations/{conversation_id}/documents/{document_id}",
    summary="Delete a file attached to a conversation and its RustFS objects",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation_document(
    conversation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: UserDep,
    conversations: ConversationServiceDep,
    documents: DocumentUploadServiceDep,
) -> None:
    try:
        await conversations.get_conversation(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    try:
        await documents.delete_conversation_document(conversation_id, user, document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from error
