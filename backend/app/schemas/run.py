import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RunCreate(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None


class RunEventOut(BaseModel):
    id: uuid.UUID
    task_id: str | None
    type: str
    data: dict[str, Any] | None
    created_at: datetime


class RunOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    query: str
    status: str
    cancel_requested: bool
    current_node: str | None
    current_activity: str | None
    plan_version: int
    replan_count: int
    answer: str | None
    citations: list[dict[str, Any]] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
