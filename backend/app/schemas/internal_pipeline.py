import uuid
from datetime import datetime
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
    """The whole output of a task at once, as workers sent it before #305 - only while they roll out."""

    logs: str


class TaskLogEntryIn(BaseModel):
    celery_task_id: str = Field(max_length=255)
    task_name: str = Field(max_length=255)
    document_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    ts: datetime
    level: str = Field(max_length=16)
    message: str
    extra: dict[str, Any] | None = None


class TaskLogEntriesIn(BaseModel):
    """A batch of lines a worker logged while running its tasks (#305)."""

    entries: list[TaskLogEntryIn] = Field(max_length=1000)


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
    # Where that passage is in the content of `source_page` (#351), when the worker knows it.
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)


class GeneratedQaReplace(BaseModel):
    """What one run of the pipeline generated (#299): the pairs of a window of a document's pages
    ("window:3-4"), of a tabular profile ("tabular"), of a collection's description ("collection:..").
    They replace what the previous run of the same key had recorded, so a task run twice leaves the
    same pairs as one run. `document_id` is None for the pairs about a whole collection."""

    document_id: uuid.UUID | None = None
    key: str = Field(min_length=1, max_length=200)
    pairs: list[GeneratedQaPair]


class ExtractedOccurrence(BaseModel):
    """Where an entity is in a page of the window (#352): an interval of characters of that page's content."""

    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ExtractedEntity(BaseModel):
    name: str
    type: EntityType
    # How many times the worker found the entity in the text of the window - or, when it found it nowhere (the
    # model normalized or translated its name), how many times the model listed it.
    mentions: int = Field(default=1, ge=1)
    # Where it found it - up to a few per page: a name that is everywhere would drown the page.
    occurrences: list[ExtractedOccurrence] = Field(default_factory=list, max_length=500)


class ExtractedRelation(BaseModel):
    # Entities are named, not identified: they are created by the same call.
    from_name: str
    to_name: str
    type: str
    # The sentence that justifies it (#352), checked in the text by the worker: the page, the sentence, and where
    # it is in that page's content.
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = Field(default=None, max_length=4000)
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)


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


class StageBegin(BaseModel):
    """A stage of the pipeline about to run for a document (#300)."""

    # Opaque to the backend: the worker's hash of the file and of the settings the stage depends on.
    fingerprint: str = Field(min_length=8, max_length=64)
    # The pieces of a stage run in pieces - the windows of pages of the QA, of the entities - which
    # complete it when all are done. Empty for a stage that is a single piece.
    expected: list[str] = Field(default_factory=list, max_length=5000)
    # The file's hash, when the worker is the one that knows it: a file hashed as it is read, a URL.
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class StageBeginOut(BaseModel):
    # True: the stage was copied from another document of the same file, nothing is left to compute.
    reused: bool


class StageDone(BaseModel):
    key: str = Field(default="_", min_length=1, max_length=200)


class StageDoneOut(BaseModel):
    """Where the stage is once the piece is done - what the worker's last piece looks at to carry on."""

    # The pieces done of those announced (0 of 0 for a stage that is a single piece, or that nobody began).
    done: int
    expected: int
    complete: bool
    # True for the one piece whose completion completed the stage.
    completed_now: bool
