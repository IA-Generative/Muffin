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
