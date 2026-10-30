import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.page_ranges import InvalidPageRangesError, parse_page_ranges
from app.models.collection import CollectionVisibility, SharePermission, ShareStatus, ShareSubjectType

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


class RelevantDocumentOut(BaseModel):
    id: uuid.UUID
    name: str


class QaPairOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    source: str | None = None
    # Where the answer comes from (#349): the document, its page and the passage - what opens the document
    # on that page with the passage highlighted. None for a pair written by hand, or one whose passage was
    # not found.
    source_document_id: uuid.UUID | None = None
    source_page: int | None = None
    source_excerpt: str | None = None
    # Where the passage is in that page's content (#351), when known: frames it at the right place.
    source_start: int | None = None
    source_end: int | None = None
    origin: str
    validated: bool
    # A test question (#260): written by a person, kept out of the retriever, used only to measure.
    golden: bool = False
    # The documents that hold the answer (a golden pair only) - what retrieval is scored against.
    relevant_documents: list[RelevantDocumentOut] = []


class QaPairCreate(BaseModel):
    """A question/answer pair written by hand. By default a reference pair: the assistant answers from
    it before searching the documents. With `golden` it is a test question instead (#260): kept out of
    the retriever, only used to measure it. `relevant_document_ids` are the documents that hold the
    answer - what retrieval is scored against; without one the pair is kept but can't be scored
    (retrieval is judged at document level), so the UI asks for at least one."""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    golden: bool = False
    relevant_document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("question", "answer")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class QaPairValidationUpdate(BaseModel):
    validated: bool


class EntityOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    mentions: int
    # How many occurrences were found in the text (#352) - what can be opened and framed. 0: the model listed the
    # entity but its name is nowhere in the text as written (normalized, translated): nothing to show.
    occurrences: int = 0


class RelationSourceOut(BaseModel):
    """The sentence that justifies a relation, and where it is (#352)."""

    document_id: uuid.UUID
    document_name: str
    page_number: int
    passage: str
    start: int | None = None
    end: int | None = None


class RelationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    from_entity: str = Field(alias="from")
    to: str
    type: str
    source: RelationSourceOut | None = None


class EntityMentionOut(BaseModel):
    """One occurrence of an entity: the document and page it is on, and where in that page's text (#352)."""

    document_id: uuid.UUID
    document_name: str
    page_number: int
    start: int
    end: int


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
    # time it changes (see the "collections" Qdrant index, §124).
    collection_qa_count: int = 3
    # Long documents (#372): above `sampling_min_pages` pages, the summary, the QA pairs and the entities do not
    # read the whole document. The defaults read everything, so nothing changes until a collection sets them.
    # The chunks always cover every page.
    sampling_min_pages: int = Field(default=100, ge=1)
    # What the summary reads: everything, a share of the document (`summary_percent`, half at the start and half at
    # the end - or `summary_head_percent` and `summary_tail_percent` when they are set, which replace it), or the
    # pages of `summary_page_ranges` ("1-5, 40-45").
    summary_mode: Literal["all", "percent", "pages"] = "all"
    summary_percent: int = Field(default=30, ge=1, le=100)
    summary_head_percent: int | None = Field(default=None, ge=0, le=100)
    summary_tail_percent: int | None = Field(default=None, ge=0, le=100)
    summary_page_ranges: str = Field(default="", max_length=500)
    # At most this many questions for a document (None: no cap) - the model may give fewer.
    qa_max_questions: int | None = Field(default=None, ge=1)
    # The share of the entity windows that are analysed, and at most this many of them (None: no cap).
    extraction_percent: int = Field(default=100, ge=1, le=100)
    extraction_max_windows: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_sampling(self) -> "PipelineWindowsOut":
        head, tail = self.summary_head_percent, self.summary_tail_percent
        if (head is not None or tail is not None) and not 1 <= (head or 0) + (tail or 0) <= 100:
            raise ValueError("summary_head_percent + summary_tail_percent must be between 1 and 100")
        try:
            ranges = parse_page_ranges(self.summary_page_ranges)
        except InvalidPageRangesError as error:
            raise ValueError(f"summary_page_ranges: {error}") from error
        if self.summary_mode == "pages" and not ranges:
            raise ValueError("summary_mode 'pages' needs summary_page_ranges")
        return self


class IndexingEstimateOut(BaseModel):
    """The calls to the language model indexing a document costs under a collection's settings (#372)."""

    pages: int
    # Whether the document is long enough for the settings that read only a part of it to apply.
    sampled: bool
    # Calls to the chat model, by step ("total" adds them up).
    chat: dict[str, int]
    # Calls to the embedding model that do not depend on how the text is cut: the summary, and a question each.
    embeddings: dict[str, int]
    # What the collection's own description, tags and reference questions may add, when the summary changes them.
    collection_max: int


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
    sampling_min_pages: int | None = None
    summary_mode: Literal["all", "percent", "pages"] | None = None
    summary_percent: int | None = None
    summary_head_percent: int | None = None
    summary_tail_percent: int | None = None
    summary_page_ranges: str | None = None
    # These four can be sent as null to remove the cap / the separate start and end.
    qa_max_questions: int | None = None
    extraction_percent: int | None = None
    extraction_max_windows: int | None = None


class IndexingEstimateRequest(BaseModel):
    """Settings typed and not saved yet, to see what they would cost before saving them."""

    pages: int = Field(ge=1, le=100_000)
    pipeline_windows: PipelineWindowsUpdate = PipelineWindowsUpdate()
    # The way the chunks are cut, when it is typed too: cutting them with the model is a call per few pages.
    chunking_strategy: Literal["paragraph", "fixed", "semantic", "llm"] | None = None


class CollectionPathItem(BaseModel):
    id: uuid.UUID
    name: str


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # Sub-collections (#215), all relative to what the caller can read: `path` is the chain of
    # ancestors from the root down to the parent, cut at the first one the caller can't read, and
    # `parent_id` is None whenever the parent itself isn't readable - a collection shared on its
    # own never reveals the tree above it. `children_count` counts readable direct children only.
    parent_id: uuid.UUID | None
    path: list[CollectionPathItem]
    children_count: int
    # Counted server-side: `documents` below isn't embedded, so a card can't count it itself.
    document_count: int
    indexed_document_count: int
    # Read access is inherited down the tree (#216): a private collection under a public one is
    # readable by everyone all the same. The nearest public ancestor, so the UI can say so -
    # None when the collection is public itself or no ancestor is.
    inherited_public_from: CollectionPathItem | None
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
    # May change it: its owner, anyone a share lets write on it or on an ancestor (#454), or an administrator.
    # What the UI offers for the living documents; settings, sharing and deletion stay with the owner.
    can_edit: bool

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
    # The model of the vectors the active index holds when it differs from embedding_model - the
    # index hasn't been rebuilt with the new model yet (#12) and search still uses this one.
    index_embedding_model: str | None = None
    reindex_required: bool
    instructions: PipelineInstructions
    generation_models: GenerationModels
    pipeline_windows: PipelineWindowsOut
    caption_engine: Literal["local", "openai"] = "local"
    caption_model: str | None = None

    @classmethod
    def from_model(
        cls,
        collection: "CollectionModel",
        viewer_id: str,
        *,
        path: list[CollectionPathItem] | None = None,
        children_count: int = 0,
        document_counts: tuple[int, int] = (0, 0),
        inherited_public_from: CollectionPathItem | None = None,
        can_edit: bool | None = None,
    ) -> "CollectionOut":
        settings = collection.settings
        path = path or []
        if can_edit is None:
            can_edit = collection.owner_id == viewer_id
        return cls(
            id=collection.id,
            name=collection.name,
            parent_id=path[-1].id if path else None,
            path=path,
            children_count=children_count,
            document_count=document_counts[0],
            indexed_document_count=document_counts[1],
            inherited_public_from=inherited_public_from,
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
            can_edit=can_edit,
            chunking_settings=ChunkingSettings(
                strategy=settings.chunking_strategy,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            ),
            embedding_model=settings.embedding_model,
            index_embedding_model=settings.index_embedding_model,
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
            caption_engine=settings.caption_engine,
            caption_model=settings.caption_model,
        )


class CollectionCreate(BaseModel):
    # Both optional - a plain "+ Nouvelle collection" click sends neither (defaults apply, same
    # as before this existed). Set from the filing review page's "Créer une collection" shortcut
    # (§122 follow-up) to pre-fill from an unfiled document's name/summary.
    name: str | None = None
    description: str | None = None
    # Creates a sub-collection (#215) under this collection, which must be one the caller owns;
    # it starts with a copy of the parent's settings.
    parent_id: uuid.UUID | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    # Moves the collection (#215): another collection the caller owns, or an explicit null to
    # move it back to the root. Leaving the field out keeps the current parent - the service
    # tells the two apart with model_fields_set.
    parent_id: uuid.UUID | None = None


class CollectionSettingsUpdate(BaseModel):
    chunking_strategy: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    embedding_model: str | None = None
    instructions: PipelineInstructions | None = None
    generation_models: GenerationModels | None = None
    pipeline_windows: PipelineWindowsUpdate | None = None
    caption_engine: Literal["local", "openai"] | None = None
    # An empty string clears it (the hub's first chat model is then used).
    caption_model: str | None = None


class VisibilityUpdate(BaseModel):
    visibility: CollectionVisibility


class ShareCreate(BaseModel):
    subject_type: ShareSubjectType
    # An email (subject_type=user) or the exact group path/name as it appears in the Keycloak
    # token's `groups` claim (subject_type=group) - never looked up, never stored as-is, see
    # app/core/sharing.py. Not re-exposed anywhere after this request.
    identifier: str
    permission: SharePermission = SharePermission.READ


class ShareUpdate(BaseModel):
    permission: SharePermission


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: ShareSubjectType
    status: ShareStatus
    permission: SharePermission
    # Non-reversible ("j***@e***.com") - see app/core/sharing.py:mask_email/mask_group. Never the
    # full email/group identifier the owner originally typed.
    display_hint: str
    created_at: datetime
    # Set when the share is on an ancestor and only applies here by inheritance (#216) - it can
    # be managed on that ancestor only, never removed from this collection.
    inherited_from: CollectionPathItem | None = None

    @classmethod
    def from_model(
        cls, share: "CollectionShareModel", *, inherited_from: CollectionPathItem | None = None
    ) -> "ShareOut":
        return cls(
            id=share.id,
            subject_type=share.subject_type,
            status=share.status,
            permission=share.permission,
            display_hint=share.display_hint,
            created_at=share.created_at,
            inherited_from=inherited_from,
        )
