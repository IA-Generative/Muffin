import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discussion_score import DiscussionScore


class DiscussionScoreRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, conversation_id: uuid.UUID, data: dict[str, Any]) -> DiscussionScore:
        score = DiscussionScore(conversation_id=conversation_id, **data)
        self.db.add(score)
        await self.db.flush()
        return score

    async def list_by_conversation(self, conversation_id: uuid.UUID) -> Sequence[DiscussionScore]:
        result = await self.db.execute(
            select(DiscussionScore)
            .where(DiscussionScore.conversation_id == conversation_id)
            .order_by(DiscussionScore.created_at.desc())
        )
        return result.scalars().all()
