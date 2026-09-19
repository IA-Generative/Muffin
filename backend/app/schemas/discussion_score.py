import uuid
from datetime import datetime

from pydantic import BaseModel


class DiscussionScoreOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime
    message_count: int
    llm_model: str
    coherent: bool
    coherence_issues: list[str]
    context_usage_score: float
    context_usage_issues: list[str]
    reasoning: str | None
