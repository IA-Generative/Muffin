import uuid
from typing import Any

from pydantic import BaseModel

from app.schemas.collection import CollectionPathItem
from app.schemas.question import Question


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
    # {role, content}, plus asked=True on an assistant message that asked questions (#344).
    history: list[dict[str, Any]]
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
    # Whether the requesting user is a platform administrator (Run.user_is_admin) - informational for
    # the worker; what an edit request is allowed to do is decided backend-side from the run row.
    user_is_admin: bool
    # Set only for a "go further" follow-up (Run.continue_exploration, #219): the collections the
    # previous answer of this conversation left unexplored, to resume the descent from. Never
    # trusted as is - the worker intersects them with the accessible set like anything else.
    resume_from_collection_ids: list[str] | None = None
    # See Run.interactive (#344).
    interactive: bool = True
    # Collections already left unexplored when the run was created (#220): the sub-collections a
    # pinned collection couldn't bring along within PINNED_DESCENDANTS_LIMIT. The run's own
    # exploration adds to them, and the union is reported back with the answer.
    unexplored_collection_ids: list[str] | None = None


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
    # Set when this run delegated an edit of a living document to the editing agent (#171) - see
    # Run.edit_proposal.
    edit_proposal: dict[str, Any] | None = None
    # See Run.unexplored_collection_ids (#219).
    unexplored_collection_ids: list[str] | None = None
    # Questions with options the assistant asks instead of answering (#344): the answer is then the same
    # questions as text, and they are kept on the message for the interface.
    questions: list[Question] | None = None


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
    # Also search every sub-collection below the given ones (#217) - opt-in, see
    # SearchService.resolve_scope for why a search never widens itself.
    include_descendants: bool = False


class QaSourceOut(BaseModel):
    document_id: uuid.UUID
    document_name: str
    page_number: int
    passage: str
    start: int | None = None
    end: int | None = None


class QaSearchResultOut(BaseModel):
    qa_pair_id: uuid.UUID
    collection_id: uuid.UUID
    # From the highest requested collection down to collection_id, inclusive (#217) - see
    # SearchService.collection_paths. Same on the two result models below.
    collection_path: list[CollectionPathItem]
    question: str
    answer: str
    score: float
    # Where the answer comes from (#351), when the pair has a page and a passage: what opens the source of a
    # cited pair on its page with the passage framed. None for a pair written by hand, or with no passage found.
    source: QaSourceOut | None = None


class SummarySearchResultOut(BaseModel):
    document_id: uuid.UUID
    collection_id: uuid.UUID
    collection_path: list[CollectionPathItem]
    name: str
    summary: str | None
    # See DocumentSummaryOut.summary_pages.
    summary_pages: list[list[int]] | None = None
    score: float


class SearchResultOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    collection_id: uuid.UUID
    collection_path: list[CollectionPathItem]
    text: str
    rank: float
    # The document page(s) this chunk spans (Chunk.extras["page_start"/"page_end"], set for both
    # file and scraped-URL documents at chunk creation time - see worker/document_process's
    # chunk_document) - lets a citation link back to a specific page, not just the document.
    page_number: int | None = None


class AccessibleCollectionOut(BaseModel):
    id: uuid.UUID
    # Raw parent link (#215), not filtered by access like CollectionOut.parent_id: the agent
    # rebuilds the tree from this list alone, and a parent missing from the list just means
    # this collection is a root as far as this user's routing is concerned.
    parent_id: uuid.UUID | None
    name: str
    description: str
    tags: list[str]
    document_count: int


class DocumentSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    summary: str | None
    # The stretches of pages the summary was made from (#372) - None: the whole document.
    summary_pages: list[list[int]] | None = None


class TabularDocumentOut(BaseModel):
    """A tabular document the research agent can query with DuckDB - the storage_key lets the
    agent load the file directly from RustFS, the profile columns give the LLM the schema it
    needs to generate SQL without a round-trip to read the file first."""

    id: uuid.UUID
    name: str
    storage_key: str
    format: str
    row_count: int
    column_count: int
    columns: list[dict[str, Any]]
    measures: list[str]
    dimensions: list[str]
    text_columns: list[str]


class DocumentPageContentOut(BaseModel):
    page_number: int
    content: str
    screenshot_url: str | None


class ConversationTitleUpdate(BaseModel):
    title: str
