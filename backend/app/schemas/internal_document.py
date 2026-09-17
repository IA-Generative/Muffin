import uuid
from typing import Any

from pydantic import BaseModel


class InternalDocumentOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    type: str
    status: str
    storage_key: str | None
    summary: str | None = None


class DocumentStatusUpdate(BaseModel):
    status: str
    progress: int | None = None
    summary: str | None = None


class DocumentPageCreate(BaseModel):
    page_number: int
    content: str
    screenshot: str | None = None


class DocumentPageOut(BaseModel):
    page_number: int
    content: str


class ChunkCreate(BaseModel):
    index: int
    text: str
    token_count: int
    extras: dict[str, Any] | None = None
    # Computed worker-side (worker/document_process, via the collection's own
    # embedding_model) and upserted into Qdrant here rather than stored in Postgres -
    # None when no LLM hub is configured, in which case this chunk is just not searchable.
    embedding: list[float] | None = None
