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
    # Prior turns of this same conversation, oldest first, this run's own (just-inserted) user
    # message excluded - lets the worker resolve a follow-up like "elle parle de quoi ?" against
    # what was actually said before, instead of analyzing it in total isolation.
    history: list[dict[str, str]]
    # Collections explicitly attached via the chat composer's "+" picker - see
    # AgentState.pinned_vdb_ids in the worker.
    pinned_collection_ids: list[str] | None
    # Snapshot of the requesting user's Keycloak groups at run creation time - see
    # Run.user_groups. The worker threads this into list_accessible_collections so
    # group-shared collections are part of the VDB routing set, not just owner/public/direct.
    user_groups: list[str] | None
    # Opt-in, per message (chat composer toggle, off by default) - see Run.web_search_enabled.
    # Gates whether the planner is even told a "web_search" tool exists.
    web_search_enabled: bool


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
    # Final verdict from worker/agent_execution/app/graph/nodes/validate_grounding.py - optional
    # so a worker build that predates this field keeps working against a newer backend.
    grounding_valid: bool | None = None
    grounding_unsupported_claims: list[str] | None = None
    grounding_research_count: int | None = None
    # Per-message metrics from generate_answer's LLM call - stored on the assistant Message row,
    # used by the quality dashboard for average latency and cost estimation.
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


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


class QaSearchResultOut(BaseModel):
    qa_pair_id: uuid.UUID
    collection_id: uuid.UUID
    question: str
    answer: str
    score: float


class SummarySearchResultOut(BaseModel):
    document_id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    summary: str | None
    score: float


class SearchResultOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    collection_id: uuid.UUID
    text: str
    rank: float
    # The document page(s) this chunk spans (Chunk.extras["page_start"/"page_end"], set for both
    # file and scraped-URL documents at chunk creation time - see worker/document_process's
    # chunk_document) - lets a citation link back to a specific page, not just the document.
    page_number: int | None = None


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
