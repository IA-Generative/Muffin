import uuid
from typing import Any

from pydantic import BaseModel


class InternalRunOut(BaseModel):
    id: uuid.UUID
    user_id: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    query: str
    status: str
    cancel_requested: bool
    plan_version: int
    replan_count: int
    research_plan: dict[str, Any] | None
    budget: dict[str, Any] | None
    pending_human_action: dict[str, Any] | None
    answer: str | None
    citations: list[dict[str, Any]] | None


class RunStatusUpdate(BaseModel):
    status: str
    current_node: str | None = None
    current_activity: str | None = None


class RunStateUpdate(BaseModel):
    """Partial update of the JSONB state blobs - only the keys the caller
    actually knows about are merged in service-side, same reasoning as
    CollectionSettings.generation_models (see CollectionRepository.update_settings)."""

    research_plan: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    pending_human_action: dict[str, Any] | None = None
    plan_version: int | None = None
    replan_count: int | None = None


class RunResultUpdate(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = []


class RunErrorUpdate(BaseModel):
    error: str


class RunEventCreate(BaseModel):
    type: str
    data: dict[str, Any] | None = None
    task_id: str | None = None


class SearchRequest(BaseModel):
    collection_ids: list[uuid.UUID]
    query: str
    limit: int = 10


class SearchResultOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    collection_id: uuid.UUID
    text: str
    rank: float


class AccessibleCollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    tags: list[str]
    document_count: int


class DocumentSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    summary: str | None


class DocumentPageContentOut(BaseModel):
    page_number: int
    content: str
    screenshot_url: str | None


class ConversationTitleUpdate(BaseModel):
    title: str
