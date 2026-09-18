import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


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
