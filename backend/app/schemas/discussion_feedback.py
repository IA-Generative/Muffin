from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DiscussionFeedbackCreate(BaseModel):
    """What the frontend sends when a user submits their holistic judgment of a conversation -
    the human counterpart to DiscussionScore (which is LLM-generated)."""

    rating: int = Field(ge=1, le=5, description="Overall satisfaction: 1 (very poor) to 5 (excellent)")
    coherent: bool = Field(description="Whether the conversation felt coherent across turns")
    context_usage_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How well the assistant used conversational context (0.0-1.0)",
    )
    comment: str | None = Field(default=None, description="Free-text comment")


class DiscussionFeedbackOut(BaseModel):
    """What the backend returns - includes the user_id so the frontend can tell its own feedback
    apart from others' (if shared conversations ever surface this)."""

    id: UUID
    conversation_id: UUID
    user_id: str
    rating: int
    coherent: bool
    context_usage_score: float | None
    comment: str | None
    created_at: datetime
    updated_at: datetime
