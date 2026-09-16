import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.models.collection import Collection as CollectionModel


class FieldStamp(BaseModel):
    updated_by: str
    updated_at: datetime


class ChunkingSettings(BaseModel):
    strategy: str
    chunk_size: int
    chunk_overlap: int


class PipelineInstructions(BaseModel):
    qa: str
    extraction: str
    chunking: str
    tagging: str


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    description_meta: FieldStamp | None
    tags: list[str]
    tags_meta: FieldStamp | None
    updated_at: datetime

    # Not wired yet - documents come first, then QA/entities/relations/chunks/evaluation.
    # Always empty for now so the response already matches the shape those phases need.
    documents: list = []
    qa_pairs: list = []
    entities: list = []
    relations: list = []
    chunks: list = []
    evaluation_runs: list = []

    chunking_settings: ChunkingSettings
    embedding_model: str
    reindex_required: bool
    instructions: PipelineInstructions

    @classmethod
    def from_model(cls, collection: "CollectionModel") -> "CollectionOut":
        settings = collection.settings
        return cls(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            description_meta=(
                FieldStamp(updated_by=collection.description_updated_by, updated_at=collection.description_updated_at)
                if collection.description_updated_by and collection.description_updated_at
                else None
            ),
            tags=[tag.tag for tag in collection.tags],
            tags_meta=(
                FieldStamp(updated_by=collection.tags_updated_by, updated_at=collection.tags_updated_at)
                if collection.tags_updated_by and collection.tags_updated_at
                else None
            ),
            updated_at=collection.updated_at,
            chunking_settings=ChunkingSettings(
                strategy=settings.chunking_strategy,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            ),
            embedding_model=settings.embedding_model,
            reindex_required=settings.reindex_required,
            instructions=PipelineInstructions(
                qa=settings.instructions_qa,
                extraction=settings.instructions_extraction,
                chunking=settings.instructions_chunking,
                tagging=settings.instructions_tagging,
            ),
        )


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
