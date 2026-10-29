import uuid

from pydantic import BaseModel, Field


class ChunkSyncIn(BaseModel):
    id: uuid.UUID = Field(description="The id of the point the other system made for it in the vector store")
    index: int = Field(ge=0)
    text: str
    token_count: int = Field(ge=0)


class DocumentSyncIn(BaseModel):
    """A file as the other system has it (#453), in one of its collections, with the chunks it cut it into."""

    collection_external_id: str = Field(min_length=1, description="Its collection, by its id in the other system")
    name: str = Field(min_length=1)
    # Where the file is, as the other system writes it: s3://<bucket>/<key>. Read there, never copied.
    storage_key: str = Field(min_length=1)
    content_hash: str | None = None
    added_by_user_id: str | None = None
    added_by_display: str | None = None
    # The text the other system extracted from the whole file: no page boundary survives its extraction.
    text: str = ""
    chunks: list[ChunkSyncIn] = Field(default_factory=list)


class DocumentSyncOut(BaseModel):
    id: uuid.UUID
    created: bool
    chunks_written: int
    chunks_removed: int
