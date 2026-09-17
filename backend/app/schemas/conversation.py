import uuid
from datetime import datetime

from pydantic import BaseModel


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
