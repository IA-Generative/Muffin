import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.feedback import FeedbackValue


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    updated_at: datetime


class ConversationUpdate(BaseModel):
    title: str


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    # Only ever set for an assistant message - lets a restored message (not just a live one
    # still in memory) render citation footnotes and fetch its execution detail.
    run_id: uuid.UUID | None = None
    citations: list[dict[str, Any]] | None = None
    # The feedback value (up/down) the current user left on this message, if any - restored
    # after a page reload so the thumbs-up/down button stays highlighted.
    feedback: FeedbackValue | None = None
