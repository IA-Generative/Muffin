import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.discussion_score_repository import DiscussionScoreRepository
from app.schemas.internal_discussion_score import (
    ConversationMessageOut,
    DiscussionScoreCreate,
)

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="Full message transcript of a conversation, oldest first - what worker/evaluation's "
    "score_discussion judges (see #31)",
    response_model=list[ConversationMessageOut],
)
async def list_conversation_messages(
    conversation_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ConversationMessageOut]:
    if await ConversationRepository(db).get_by_id(conversation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    rows = await ConversationRepository(db).list_messages(conversation_id)
    return [ConversationMessageOut(role=message.role, content=message.content) for message, _citations in rows]


@router.post(
    "/conversations/{conversation_id}/discussion-scores",
    summary="Record a completed discussion-quality judgment for a conversation (see #31)",
    status_code=status.HTTP_201_CREATED,
)
async def create_discussion_score(
    conversation_id: uuid.UUID,
    body: DiscussionScoreCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    if await ConversationRepository(db).get_by_id(conversation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    score = await DiscussionScoreRepository(db).create(conversation_id, body.model_dump(mode="python"))
    await db.commit()
    return {"status": "ok", "id": str(score.id)}


@router.get(
    "/conversations/{conversation_id}/discussion-scores/exists",
    summary="Check whether a score already exists for this (conversation, content_hash, model) triple "
    "- lets score_discussion skip re-judging an unchanged conversation with the same model",
)
async def find_discussion_score(
    conversation_id: uuid.UUID,
    content_hash: str,
    llm_model: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | None]:
    if await ConversationRepository(db).get_by_id(conversation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    score = await DiscussionScoreRepository(db).find_existing(conversation_id, content_hash, llm_model)
    return {"id": str(score.id) if score else None}
