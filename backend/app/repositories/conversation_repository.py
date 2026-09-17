import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, conversation_id: uuid.UUID, user_id: str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_owner(self, user_id: str, *, limit: int, offset: int) -> tuple[Sequence[Conversation], int]:
        """Most recently active first - "active" meaning its last message, not just when the
        conversation row itself was last touched (title generation, say), since that's what a
        chat sidebar means by "recent"."""
        where = Conversation.user_id == user_id
        total = await self.db.scalar(select(func.count()).select_from(Conversation).where(where))

        last_message_at = (
            select(Message.conversation_id, func.max(Message.created_at).label("last_at"))
            .group_by(Message.conversation_id)
            .subquery()
        )
        result = await self.db.execute(
            select(Conversation)
            .outerjoin(last_message_at, last_message_at.c.conversation_id == Conversation.id)
            .where(where)
            .order_by(func.coalesce(last_message_at.c.last_at, Conversation.updated_at).desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total or 0

    async def list_messages(self, conversation_id: uuid.UUID) -> Sequence[Message]:
        result = await self.db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
        return result.scalars().all()

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        """No owner check - internal/worker use only, never exposed on a user-facing route."""
        result = await self.db.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()

    async def set_generated_title(self, conversation: Conversation, title: str) -> None:
        conversation.title = title
        conversation.title_generated = True

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def add_message(self, conversation_id: uuid.UUID, role: MessageRole, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self.db.add(message)
        await self.db.flush()
        return message
