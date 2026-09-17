import uuid

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


class DocumentErrorUpdate(BaseModel):
    error: str


class DocumentTagsUpdate(BaseModel):
    tags: list[str]


class QaPairCreate(BaseModel):
    document_id: uuid.UUID | None = None
    question: str
    answer: str


class EntityCreate(BaseModel):
    name: str
    type: str
    mentions_delta: int = 1


class RelationCreate(BaseModel):
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


class LlmEmbedRequest(BaseModel):
    model: str
    input: str


class LlmEmbedResponse(BaseModel):
    embedding: list[float]
