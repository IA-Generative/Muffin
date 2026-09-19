import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.feedback import FeedbackReasonCode, FeedbackValue


class FeedbackSourceIn(BaseModel):
    title: str
    url: str


class FeedbackCreate(BaseModel):
    value: FeedbackValue
    # Only ever populated alongside a "down" (see FeedbackModal.vue) - never required, a plain
    # thumbs up has none.
    reasons: list[FeedbackReasonCode] = []
    comment: str | None = None
    # Ids of Source rows already cited on this message (see #39) that the reviewer confirmed as
    # correct - re-verified server-side against message_sources before being trusted, never taken
    # at face value (see RunService.submit_feedback).
    validated_source_ids: list[uuid.UUID] = []
    # A brand-new source the reviewer suggests, not one already cited - always has a url (a
    # reviewer names a page, not an existing chunk), never document_id/chunk_id.
    added_sources: list[FeedbackSourceIn] = []


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    value: FeedbackValue
    reasons: list[FeedbackReasonCode]
    comment: str | None
    validated_source_ids: list[uuid.UUID]
    added_source_ids: list[uuid.UUID]
    created_at: datetime


class FeedbackStatsOut(BaseModel):
    up_count: int
    down_count: int
    # Only counts reasons attached to a "down" - a reason code is never attached to a "up".
    reason_counts: dict[FeedbackReasonCode, int]
