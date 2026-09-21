import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.collection import CollectionVisibility, ShareStatus, ShareSubjectType

if TYPE_CHECKING:
    from app.models.collection import Collection as CollectionModel
    from app.models.collection import CollectionShare as CollectionShareModel


class FieldStamp(BaseModel):
    updated_by: str
    updated_at: datetime


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_name: str
    index: int
    text: str
    token_count: int


class GroundednessRunOut(BaseModel):
    run_id: uuid.UUID
    query: str
    created_at: datetime
    unsupported_claims: list[str]


class GroundednessStatsOut(BaseModel):
    # Runs with a grounding verdict at all (i.e. completed with an answer) that cited this
    # collection - see Run.grounding_valid. Zero doesn't mean "perfect", it means "no data yet".
    evaluated_count: int
    ungrounded_count: int
    # Most recent runs whose answer contained at least one unsupported claim, for a human to
    # actually look at rather than just a raw ratio - see RunRepository.get_groundedness_stats.
    recent_ungrounded: list[GroundednessRunOut]


class QaPairOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    source: str | None = None
    origin: str
    validated: bool


class EntityOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    mentions: int


class RelationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    from_entity: str = Field(alias="from")
    to: str
    type: str


class ChunkingSettings(BaseModel):
    strategy: str
    chunk_size: int
    chunk_overlap: int


class PipelineInstructions(BaseModel):
    qa: str
    extraction: str
    chunking: str
    tagging: str
    summary: str


class GenerationModels(BaseModel):
    qa: str | None = None
    extraction: str | None = None
    chunking: str | None = None
    tagging: str | None = None
    summary: str | None = None


class PipelineWindowsOut(BaseModel):
    """Sliding-window params for the steps that read several pages at once.
    Defaults here (not on the DB column) are the actual defaults - a fresh
    collection has pipeline_windows=None and gets these until the user saves
    a card that overrides one."""

    summary_pages_per_map: int = 5
    qa_window_pages: int = 2
    qa_slide_pages: int = 1
    qa_questions_per_window: int = 3
    extraction_window_pages: int = 4
    extraction_slide_pages: int = 1
    chunking_window_pages: int = 2
    chunking_slide_pages: int = 1
    # Not a document-level step like the others above - how many QA pairs
    # generate_collection_qa produces from the collection's description each
    # time it changes (see the "collections" Meilisearch index, §124).
    collection_qa_count: int = 3


class PipelineWindowsUpdate(BaseModel):
    summary_pages_per_map: int | None = None
    qa_window_pages: int | None = None
    qa_slide_pages: int | None = None
    qa_questions_per_window: int | None = None
    extraction_window_pages: int | None = None
    extraction_slide_pages: int | None = None
    chunking_window_pages: int | None = None
    chunking_slide_pages: int | None = None
    collection_qa_count: int | None = None


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    description_meta: FieldStamp | None
    tags: list[str]
    tags_meta: FieldStamp | None
    updated_at: datetime
    visibility: CollectionVisibility
    # How the caller can see this collection at all - owner (full read/write), public (anyone,
    # read-only) or shared (an ACTIVE CollectionShare, read-only). Drives which actions the UI
    # offers (settings/reindex/delete/sharing are owner-only, see CollectionService._get_owned).
    is_owner: bool

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
    generation_models: GenerationModels
    pipeline_windows: PipelineWindowsOut

    @classmethod
    def from_model(cls, collection: "CollectionModel", viewer_id: str) -> "CollectionOut":
        settings = collection.settings
        return cls(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            description_meta=(
                FieldStamp(
                    updated_by=collection.description_updated_by,
                    updated_at=collection.description_updated_at,
                )
                if collection.description_updated_by and collection.description_updated_at
                else None
            ),
            tags=[tag.tag for tag in collection.tags],
            tags_meta=(
                FieldStamp(
                    updated_by=collection.tags_updated_by,
                    updated_at=collection.tags_updated_at,
                )
                if collection.tags_updated_by and collection.tags_updated_at
                else None
            ),
            updated_at=collection.updated_at,
            visibility=collection.visibility,
            is_owner=collection.owner_id == viewer_id,
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
                summary=settings.instructions_summary,
            ),
            generation_models=GenerationModels(**(settings.generation_models or {})),
            pipeline_windows=PipelineWindowsOut(**(settings.pipeline_windows or {})),
        )


class CollectionCreate(BaseModel):
    # Both optional - a plain "+ Nouvelle collection" click sends neither (defaults apply, same
    # as before this existed). Set from the filing review page's "Créer une collection" shortcut
    # (§122 follow-up) to pre-fill from an unfiled document's name/summary.
    name: str | None = None
    description: str | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class CollectionSettingsUpdate(BaseModel):
    chunking_strategy: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    embedding_model: str | None = None
    instructions: PipelineInstructions | None = None
    generation_models: GenerationModels | None = None
    pipeline_windows: PipelineWindowsUpdate | None = None


class VisibilityUpdate(BaseModel):
    visibility: CollectionVisibility


class ShareCreate(BaseModel):
    subject_type: ShareSubjectType
    # An email (subject_type=user) or the exact group path/name as it appears in the Keycloak
    # token's `groups` claim (subject_type=group) - never looked up, never stored as-is, see
    # app/core/sharing.py. Not re-exposed anywhere after this request.
    identifier: str


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: ShareSubjectType
    status: ShareStatus
    # Non-reversible ("j***@e***.com") - see app/core/sharing.py:mask_email/mask_group. Never the
    # full email/group identifier the owner originally typed.
    display_hint: str
    created_at: datetime

    @classmethod
    def from_model(cls, share: "CollectionShareModel") -> "ShareOut":
        return cls(
            id=share.id,
            subject_type=share.subject_type,
            status=share.status,
            display_hint=share.display_hint,
            created_at=share.created_at,
        )
