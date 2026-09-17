import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import ConversationOut, MessageOut
from app.schemas.pagination import Page, PaginationParams


class ConversationNotFoundError(Exception):
    pass


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationRepository(db)

    async def list_conversations(self, user: RequestContext, pagination: PaginationParams) -> Page[ConversationOut]:
        items, total = await self.conversations.list_by_owner(
            user.user_id, limit=pagination.limit, offset=pagination.offset
        )
        out = [ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at) for c in items]
        return pagination.to_page(out, total)

    async def list_messages(self, conversation_id: uuid.UUID, user: RequestContext) -> list[MessageOut]:
        conversation = await self.conversations.get(conversation_id, user.user_id)
        if conversation is None:
            raise ConversationNotFoundError(str(conversation_id))
        rows = await self.conversations.list_messages(conversation_id)
        return [
            MessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                run_id=message.run_id,
                citations=citations,
            )
            for message, citations in rows
        ]
