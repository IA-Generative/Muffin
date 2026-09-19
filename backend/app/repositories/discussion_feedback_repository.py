import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discussion_feedback import DiscussionFeedback


class DiscussionFeedbackRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, conversation_id: uuid.UUID, user_id: str, data: dict[str, Any]) -> DiscussionFeedback:
        """Creates or updates the user's feedback for this conversation - one feedback per user
        per conversation, re-submitting overwrites the previous judgment."""
        existing = await self.find_by_user(conversation_id, user_id)
        if existing is not None:
            for key, value in data.items():
                setattr(existing, key, value)
            await self.db.flush()
            return existing
        feedback = DiscussionFeedback(conversation_id=conversation_id, user_id=user_id, **data)
        self.db.add(feedback)
        await self.db.flush()
        return feedback

    async def find_by_user(self, conversation_id: uuid.UUID, user_id: str) -> DiscussionFeedback | None:
        result = await self.db.execute(
            select(DiscussionFeedback).where(
                DiscussionFeedback.conversation_id == conversation_id,
                DiscussionFeedback.user_id == user_id,
            )
        )
        return result.scalars().first()

    async def list_by_conversation(self, conversation_id: uuid.UUID) -> Sequence[DiscussionFeedback]:
        result = await self.db.execute(
            select(DiscussionFeedback)
            .where(DiscussionFeedback.conversation_id == conversation_id)
            .order_by(DiscussionFeedback.created_at.desc())
        )
        return result.scalars().all()
