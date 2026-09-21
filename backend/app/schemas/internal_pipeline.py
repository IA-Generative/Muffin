import uuid
from typing import Any

from pydantic import BaseModel


class CollectionSettingsInternalOut(BaseModel):
    """What the worker needs to run the post-chunking pipeline for a
    document: chunking parameters, sliding-window sizes, per-step models and
    instructions. Not the user-facing CollectionOut shape - no tags/QA/etc."""

    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    instructions: dict[str, str]
    generation_models: dict[str, str | None]
    pipeline_windows: dict[str, int]


class TaskCreate(BaseModel):
    celery_task_id: str
    task_name: str
    document_id: uuid.UUID
    # Links this task under the run that spawned it (e.g. chunk_document is a
    # child of process_document) so the UI can group a pipeline run together.
    parent_celery_task_id: str | None = None


class TaskLogsUpdate(BaseModel):
    logs: str


class DocumentSummaryUpdate(BaseModel):
    summary: str
    # Computed worker-side (same pattern as ChunkCreate.embedding/QaPairCreate.embedding) - backs
    # the research agent's tier-2 retrieval (§ QA -> summaries -> chunks): the top-K most
    # relevant document summaries are found by vector search, not by reading every summary in
    # the collection, so it stays cheap regardless of how many documents the collection has.
    embedding: list[float] | None = None


class DocumentErrorUpdate(BaseModel):
    error: str


class DocumentTagsUpdate(BaseModel):
    tags: list[str]


class QaPairCreate(BaseModel):
    document_id: uuid.UUID | None = None
    question: str
    answer: str
    # Computed worker-side (same pattern as ChunkCreate.embedding) - a QA pair with none is just
    # never surfaced by the research agent's QA-first retrieval tier, it still exists otherwise.
    embedding: list[float] | None = None


class EntityCreate(BaseModel):
    document_id: uuid.UUID
    name: str
    type: str
    mentions_delta: int = 1


class RelationCreate(BaseModel):
    document_id: uuid.UUID | None = None
    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    type: str


class LlmChatMessage(BaseModel):
    role: str
    content: str


class LlmChatRequest(BaseModel):
    model: str
    messages: list[LlmChatMessage]
    max_tokens: int | None = None


class LlmChatResponse(BaseModel):
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class EntityOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    mentions: int


class CollectionMetadataOut(BaseModel):
    """What the worker needs to decide whether the collection's
    description/tags should change: their current values, plus every
    document summary produced so far (used to synthesize them the first
    time, before there's a description/tags to incrementally revise)."""

    description: str
    tags: list[str]
    document_summaries: list[str]


class CollectionDescriptionUpdate(BaseModel):
    description: str


class CollectionTagsUpdate(BaseModel):
    tags: list[str]


class CollectionDescriptionEmbeddingUpdate(BaseModel):
    model: str
    embedding: list[float]


class CollectionSearchResultOut(BaseModel):
    collection_id: uuid.UUID
    score: float


class ColumnStatsIn(BaseModel):
    name: str
    type: str
    semantic_type: str = "other"
    null_count: int
    distinct_count: int
    top_values: list[dict[str, Any]] = []
    numeric_stats: dict[str, float | int | None] | None = None
    date_stats: dict[str, str | None] | None = None
    text_stats: dict[str, int | float | None] | None = None


class TabularProfileCreate(BaseModel):
    """Profil tabulaire envoyé par le worker document_process après analyse
    DuckDB d'un fichier CSV/XLSX/Parquet/JSON - voir issue #69."""

    row_count: int
    column_count: int
    columns: list[ColumnStatsIn]
    sample_rows: list[dict[str, Any]]
    format: str
    measures: list[str] = []
    dimensions: list[str] = []
    text_columns: list[str] = []


class LlmEmbedRequest(BaseModel):
    model: str
    input: str


class LlmEmbedResponse(BaseModel):
    embedding: list[float]
