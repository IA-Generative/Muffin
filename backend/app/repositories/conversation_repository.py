import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run


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

    async def list_messages(self, conversation_id: uuid.UUID) -> Sequence[tuple[Message, list[dict] | None]]:
        """Joined to Run rather than storing citations on Message too - Run is already the
        source of truth for them (§ conversation persistence), and a message never outlives the
        run that produced it in any way that would make them diverge."""
        result = await self.db.execute(
            select(Message, Run.citations)
            .outerjoin(Run, Message.run_id == Run.id)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return result.all()

    async def get_assistant_message_by_run_id(self, run_id: uuid.UUID) -> Message | None:
        """The assistant's answer message for a run - not Run.message_id, which is the *user*
        message that triggered it (see Run.message_id's docstring). This is what a feedback
        (always given on the answer, never the question) attaches to."""
        result = await self.db.execute(
            select(Message).where(Message.run_id == run_id, Message.role == MessageRole.ASSISTANT)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, conversation_id: uuid.UUID) -> Conversation | None:
        """No owner check - internal/worker use only, never exposed on a user-facing route."""
        result = await self.db.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()

    async def set_generated_title(self, conversation: Conversation, title: str) -> None:
        conversation.title = title
        conversation.title_generated = True

    async def delete(self, conversation: Conversation) -> None:
        await self.db.delete(conversation)

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def add_message(
        self, conversation_id: uuid.UUID, role: MessageRole, content: str, run_id: uuid.UUID | None = None
    ) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content, run_id=run_id)
        self.db.add(message)
        await self.db.flush()
        return message
