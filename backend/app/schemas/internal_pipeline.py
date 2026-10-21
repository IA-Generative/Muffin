import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.entity import EntityType


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
    # The model the worker made the vector with - redone with the index's own model when it differs
    # (a vector computed just before the index was rebuilt with a new one, #12).
    embedding_model: str | None = None


class DocumentErrorUpdate(BaseModel):
    error: str


class DocumentTagsUpdate(BaseModel):
    tags: list[str]


class GeneratedQaPair(BaseModel):
    question: str
    answer: str
    # Computed worker-side (same pattern as ChunkCreate.embedding) - a QA pair with none is just
    # never surfaced by the research agent's QA-first retrieval tier, it still exists otherwise.
    embedding: list[float] | None = None
    # The model the worker made the vector with - redone with the index's own model when it differs
    # (a vector computed just before the index was rebuilt with a new one, #12).
    embedding_model: str | None = None
    # Where in the document the answer comes from (#126), when the worker could tell.
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = Field(default=None, max_length=4000)


class GeneratedQaReplace(BaseModel):
    """What one run of the pipeline generated (#299): the pairs of a window of a document's pages
    ("window:3-4"), of a tabular profile ("tabular"), of a collection's description ("collection:..").
    They replace what the previous run of the same key had recorded, so a task run twice leaves the
    same pairs as one run. `document_id` is None for the pairs about a whole collection."""

    document_id: uuid.UUID | None = None
    key: str = Field(min_length=1, max_length=200)
    pairs: list[GeneratedQaPair]


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType
    mentions: int = Field(default=1, ge=1)


class ExtractedRelation(BaseModel):
    # Entities are named, not identified: they are created by the same call.
    from_name: str
    to_name: str
    type: str


class EntityWindowReplace(BaseModel):
    """What was extracted from one window of a document's pages (#299), in place of what the previous
    extraction of that window recorded."""

    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation] = Field(default_factory=list)


class Prune(BaseModel):
    # How many pages (the first ones), or chunks, of a document to keep: what a previous, longer run
    # left after them goes (#299).
    keep: int = Field(ge=0)


class LlmChatMessage(BaseModel):
    role: str
    content: str


class LlmUsageContext(BaseModel):
    """What a worker's LLM call is for, so the proxy can record who it was consumed for (see
    UsageService.record). Every field optional: a call with no context is still recorded, just
    not attributed to anyone."""

    step: str | None = None
    user_id: str | None = None
    run_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None


class LlmChatRequest(BaseModel):
    model: str
    messages: list[LlmChatMessage]
    max_tokens: int | None = None
    usage: LlmUsageContext | None = None


class LlmChatResponse(BaseModel):
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class SubCollectionDescriptionOut(BaseModel):
    name: str
    description: str


class CollectionMetadataOut(BaseModel):
    """What the worker needs to decide whether the collection's
    description/tags should change: their current values, plus every
    document summary produced so far (used to synthesize them the first
    time, before there's a description/tags to incrementally revise)."""

    description: str
    tags: list[str]
    document_summaries: list[str]
    # Direct sub-collections that already have a description (#218) - what a parent's
    # description is rolled up from, alongside its own document summaries.
    sub_collections: list[SubCollectionDescriptionOut] = []


class CollectionDescriptionUpdate(BaseModel):
    description: str


class CollectionTagsUpdate(BaseModel):
    tags: list[str]


class CollectionDescriptionEmbeddingUpdate(BaseModel):
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
    usage: LlmUsageContext | None = None


class LlmEmbedBatchRequest(BaseModel):
    model: str
    inputs: list[str] = Field(min_length=1, max_length=256)
    usage: LlmUsageContext | None = None


class LlmEmbedBatchResponse(BaseModel):
    embeddings: list[list[float]]


class LlmEmbedResponse(BaseModel):
    embedding: list[float]
