import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.feedback import FeedbackReasonCode, FeedbackValue


class FeedbackCreate(BaseModel):
    value: FeedbackValue
    # Only ever populated alongside a "down" (see FeedbackModal.vue) - never required, a plain
    # thumbs up has none.
    reasons: list[FeedbackReasonCode] = []
    comment: str | None = None


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    value: FeedbackValue
    reasons: list[FeedbackReasonCode]
    comment: str | None
    created_at: datetime


class FeedbackStatsOut(BaseModel):
    up_count: int
    down_count: int
    # Only counts reasons attached to a "down" - a reason code is never attached to a "up".
    reason_counts: dict[FeedbackReasonCode, int]
