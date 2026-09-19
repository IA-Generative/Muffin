import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Feedback, FeedbackReason, FeedbackReasonCode, FeedbackValue

# Same citations[].vdb_id matching as RunRepository.get_groundedness_stats - the only real link
# between a run and a collection (a run's pinned_collection_ids is what the user attached, not
# necessarily what actually got cited).
_CITED_COLLECTION = (
    "EXISTS (SELECT 1 FROM jsonb_array_elements(runs.citations) AS c WHERE c ->> 'vdb_id' = :collection_id)"
)


class FeedbackRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        message_id: uuid.UUID,
        user_id: str,
        value: FeedbackValue,
        reasons: list[FeedbackReasonCode],
        comment: str | None,
    ) -> Feedback:
        feedback = Feedback(message_id=message_id, user_id=user_id, value=value, comment=comment)
        self.db.add(feedback)
        await self.db.flush()
        for reason in reasons:
            self.db.add(FeedbackReason(feedback_id=feedback.id, reason=reason))
        await self.db.flush()
        return feedback

    async def get_stats(self, collection_id: uuid.UUID) -> dict[str, Any]:
        """Aggregates feedback (see Feedback.value) left on every assistant message whose run
        cited this collection."""
        counts = await self.db.execute(
            text(
                f"""
                SELECT
                    count(*) FILTER (WHERE feedbacks.value = 'UP') AS up_count,
                    count(*) FILTER (WHERE feedbacks.value = 'DOWN') AS down_count
                FROM feedbacks
                JOIN messages ON messages.id = feedbacks.message_id
                JOIN runs ON runs.id = messages.run_id
                WHERE {_CITED_COLLECTION}
                """
            ).bindparams(collection_id=str(collection_id))
        )
        up_count, down_count = counts.one()

        reason_rows = await self.db.execute(
            text(
                f"""
                SELECT feedback_reasons.reason AS reason, count(*) AS reason_count
                FROM feedback_reasons
                JOIN feedbacks ON feedbacks.id = feedback_reasons.feedback_id
                JOIN messages ON messages.id = feedbacks.message_id
                JOIN runs ON runs.id = messages.run_id
                WHERE {_CITED_COLLECTION}
                GROUP BY feedback_reasons.reason
                """
            ).bindparams(collection_id=str(collection_id))
        )
        # SQLAlchemy's Enum(FeedbackReasonCode, ...) stores the Python member's *name* ("INCORRECT_
        # ANSWER"), not its value ("incorrect_answer") - a raw-SQL result set bypasses that
        # translation, so it has to be done by hand here.
        reason_counts = {FeedbackReasonCode[row.reason]: row.reason_count for row in reason_rows}

        return {"up_count": up_count or 0, "down_count": down_count or 0, "reason_counts": reason_counts}
