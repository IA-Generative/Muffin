import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.conversation import ConversationOut, MessageOut
from app.schemas.pagination import Page, PaginationParams
from app.services.conversation_service import ConversationNotFoundError, ConversationService

router = APIRouter(tags=["Conversations"])


def get_conversation_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ConversationService:
    return ConversationService(db)


ServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/conversations",
    summary="List the user's conversations, most recently active first",
    response_model=Page[ConversationOut],
)
async def list_conversations(
    user: UserDep, service: ServiceDep, pagination: Annotated[PaginationParams, Depends()]
) -> Page[ConversationOut]:
    return await service.list_conversations(user, pagination)


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="List a conversation's messages, oldest first - used to restore a chat thread",
    response_model=list[MessageOut],
)
async def list_conversation_messages(
    conversation_id: uuid.UUID, user: UserDep, service: ServiceDep
) -> list[MessageOut]:
    try:
        return await service.list_messages(conversation_id, user)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
