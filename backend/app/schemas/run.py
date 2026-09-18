import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RunCreate(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    # Collections explicitly attached via the chat composer's "+" picker - always searched
    # regardless of what the agent's own VDB relevance routing would have picked on its own.
    collection_ids: list[uuid.UUID] | None = None


class RunResumeRequest(BaseModel):
    answer: str


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
    pending_human_action: dict[str, Any] | None
    answer: str | None
    citations: list[dict[str, Any]] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
