import uuid
from datetime import UTC, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    # "standard" or "living" (#166) - a living document has a revision history.
    kind: str = "standard"
    status: str
    progress: int
    # Filing suggestion (§122) - all None for a document created before this existed, or one
    # that was never uploaded straight into a conversation (a regular collection upload has no
    # temporary-collection detour to suggest filing out of in the first place).
    added_by_display: str | None = None
    suggested_collection_id: uuid.UUID | None = None
    suggested_collection_name: str | None = None
    suggested_collection_score: float | None = None
    # Top-K behind suggested_collection_id/score (which is just candidates[0]) - a point-in-time
    # snapshot (collection_id/name/description/score), see Document.filing_candidates.
    filing_candidates: list[dict[str, Any]] | None = None
    filing_dismissed: bool = False


class DocumentLockOut(BaseModel):
    """Who is editing a living document and until when (#170) - never carries the token, which
    only the holder gets (see DocumentLockGrantOut)."""

    locked_by_display: str | None
    expires_at: datetime
    # True when the lock belongs to the calling user - e.g. their own session in another tab.
    held_by_me: bool

    @classmethod
    def from_document(cls, document: Any, user_id: str, now: datetime) -> "DocumentLockOut | None":
        if document.lock_expires_at is None or document.lock_expires_at <= now:
            return None
        return cls(
            locked_by_display=document.locked_by_display,
            expires_at=document.lock_expires_at,
            held_by_me=document.locked_by_user_id == user_id,
        )


class DocumentLockGrantOut(DocumentLockOut):
    token: str


class DocumentDetailOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    kind: str = "standard"
    # Number of the current revision - None for a standard document.
    current_revision: int | None = None
    lock: DocumentLockOut | None = None
    status: str
    progress: int
    summary: str | None
    # The stretches of pages the summary was made from, [[first, last], ...] - None when it read the whole document.
    summary_pages: list[list[int]] | None = None
    error: str | None
    tags: list[str]
    page_count: int


class DocumentPageOut(BaseModel):
    page_number: int
    content: str
    screenshot_url: str | None


class RegionOut(BaseModel):
    """A region of the layout of a scanned page (#409), box normalized between 0 and 1 against the page."""

    id: uuid.UUID
    page_number: int
    # Reading order within the page, from 0.
    position: int
    type: str
    score: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    polygon: list[tuple[float, float]] | None = None
    title_level: int | None = None
    caption: str | None = None
    caption_model: str | None = None


class TableSummaryOut(BaseModel):
    """A table read on a scanned page (#410), without its content: what tells that it is there and what it is about."""

    # `<document>/p<page>/t<rank>` - what the page's text says in its `[Tableau ...]` marker.
    table_id: str
    page_number: int
    rank: int
    n_rows: int
    n_cols: int
    has_header: bool
    headers: list[str] | None = None
    # False when the structure is doubtful: the content is there, to be read with care.
    reliable: bool
    score: float


class TableCellOut(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str = ""


class TableOut(TableSummaryOut):
    """A table with its content: the grid, and that grid as Markdown and as HTML (which the Markdown cannot be when a
    cell spans several rows or columns)."""

    cells: list[TableCellOut]
    markdown: str
    html: str
    model_version: str = ""


class DocumentUrlCreate(BaseModel):
    url: str
    # Asked when the URL is added (#19): when its page is fetched again. None: never.
    refresh_schedule: "RefreshSchedule | None" = None
    # The collection already has this URL (#300): refused unless this is set, once the user confirmed.
    allow_duplicate: bool = False


class FilingCandidateOut(BaseModel):
    """A document its uploader still hasn't filed into a permanent collection they control
    (§122) - the "Fichiers à ranger" review page's row shape. Not DocumentOut: this needs the
    *current* collection's own name/editability, which DocumentOut (used for an ordinary
    collection's document list, where that's always implicitly "yes, this very collection") has
    no reason to carry."""

    id: uuid.UUID
    name: str
    added_by_display: str | None
    collection_id: uuid.UUID
    collection_name: str
    collection_is_temporary: bool
    collection_editable: bool
    suggested_collection_id: uuid.UUID | None
    suggested_collection_name: str | None
    suggested_collection_score: float | None
    filing_candidates: list[dict[str, Any]] | None
    filing_dismissed: bool
    created_at: datetime


class FilingDecision(BaseModel):
    action: str  # "accept" | "choose_other" | "dismiss"
    target_collection_id: uuid.UUID | None = None


class TabularSheetOut(BaseModel):
    """A sheet of a tabular file (#431): what the analysis found in it, column by column, and a few rows."""

    model_config = ConfigDict(from_attributes=True)

    index: int
    name: str
    hidden: bool
    # Rows of data (the header is not one).
    rows: int
    header_detected: bool
    # The sheet is longer than the analysis' bound: only its first rows are described and queryable.
    truncated: bool
    columns: list[dict[str, Any]]
    preview: list[list[Any]]
    warnings: list[str]
    # {"rows", "columns": [{"name", "sql_type"}]} of the typed copy that SQL reads; None when there is none.
    table: dict[str, Any] | None = None


class TabularProfileOut(BaseModel):
    """Profil statistique d'un document tabulaire, exposé au frontend
    pour afficher le schéma, les stats, la classification et un échantillon
    de lignes."""

    model_config = ConfigDict(from_attributes=True)

    row_count: int
    column_count: int
    format: str
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    measures: list[str]
    dimensions: list[str]
    text_columns: list[str]
    # Of the shape of `sheets` (#431). None: a profile from before the sheets were kept, which has none.
    analysis_version: int | None = None
    # Every sheet of the file, in its order - the profile above describes the main one.
    sheets: list[TabularSheetOut] = []


class MarkdownDocumentCreate(BaseModel):
    """A Markdown living document written from scratch (#172) - content can't be empty, there
    would be nothing to index."""

    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)

    @field_validator("name", "content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DocumentRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    filename: str
    format: str
    origin: str
    created_by_display: str | None
    restored_from_number: int | None
    created_at: datetime
    is_current: bool = False


# -- scheduled refresh of a URL document (#19) --------------------------------------------------


class RefreshSchedule(BaseModel):
    """When a URL document's page is fetched again: once at a date and time, every day or on some
    days of the week at a time, or every N minutes. Every time is on the hour or at half past - when
    the scan runs (app/models/document_refresh_schedule.py)."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["once", "daily", "weekly", "interval"]
    # once: when (in the future).
    run_at: datetime | None = None
    # daily, weekly: at what time, in `timezone`.
    time_of_day: time | None = None
    # weekly: which days, 0 = Monday.
    weekdays: list[int] | None = None
    # interval: how often, a multiple of 30 minutes, up to a week.
    interval_minutes: int | None = None
    # The owner's time zone (the browser's): what time_of_day means.
    timezone: str = "Europe/Paris"

    @model_validator(mode="after")
    def _complete(self) -> "RefreshSchedule":
        from app.models.document_refresh_schedule import MAX_INTERVAL_MINUTES, SCAN_MINUTES

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown time zone {self.timezone!r}") from error
        on_grid = "must be on the hour or at half past"
        if self.kind == "once":
            if self.run_at is None or self.run_at.tzinfo is None:
                raise ValueError("run_at (with a time zone) is required")
            if self.run_at.minute % SCAN_MINUTES or self.run_at.second or self.run_at.microsecond:
                raise ValueError(f"run_at {on_grid}")
            if self.run_at <= datetime.now(UTC):
                raise ValueError("run_at must be in the future")
            self.time_of_day, self.weekdays, self.interval_minutes = None, None, None
        elif self.kind in ("daily", "weekly"):
            if self.time_of_day is None:
                raise ValueError("time_of_day is required")
            if self.time_of_day.minute % SCAN_MINUTES or self.time_of_day.second:
                raise ValueError(f"time_of_day {on_grid}")
            if self.kind == "weekly":
                if not self.weekdays or any(day not in range(7) for day in self.weekdays):
                    raise ValueError("weekdays: at least one day, 0 (Monday) to 6 (Sunday)")
                self.weekdays = sorted(set(self.weekdays))
            else:
                self.weekdays = None
            self.run_at, self.interval_minutes = None, None
        else:
            minutes = self.interval_minutes
            if minutes is None or minutes <= 0 or minutes % SCAN_MINUTES or minutes > MAX_INTERVAL_MINUTES:
                raise ValueError(f"interval_minutes: a multiple of {SCAN_MINUTES}, up to {MAX_INTERVAL_MINUTES}")
            self.run_at, self.time_of_day, self.weekdays = None, None, None
        return self


class RefreshScheduleOut(BaseModel):
    # None: no automatic refresh.
    schedule: RefreshSchedule | None
    next_run_at: datetime | None
    # When the page was last fetched - by its indexing or by a refresh check.
    last_fetched_at: datetime | None


class RefreshScheduleUpdate(BaseModel):
    # None to stop refreshing.
    schedule: RefreshSchedule | None


class ContentHashIn(BaseModel):
    # SHA-256 (hex) of the page as the worker extracted it - or of the file, for a URL serving one.
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Where the worker stored the file a URL served (PDF, Office, image, text, tabular), processed
    # like an upload from there. None for an HTML page.
    storage_key: str | None = None


class UrlRefreshClaimOut(BaseModel):
    document_ids: list[uuid.UUID]


class UrlFetchReportOut(BaseModel):
    # The page differs from what is indexed: the document is being reprocessed.
    changed: bool


# DocumentUrlCreate refers to RefreshSchedule, defined after it.
DocumentUrlCreate.model_rebuild()


class ReprocessedOut(BaseModel):
    """How many documents in error were relaunched (#340)."""

    reprocessed: int


class HighlightRequest(BaseModel):
    """What to frame on a page (#350): a passage - found in the page's text -, an interval of characters of it, or
    a cited chunk (#353), which says where it is in each page it touches. A POST, though it only reads: a cited
    chunk's text is long, and would not fit in the address."""

    text: str | None = Field(default=None, max_length=20_000)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    chunk_id: uuid.UUID | None = None
    # A short text that is several times on the page (a name): how many of its occurrences, at most.
    max_occurrences: int = Field(default=1, ge=1, le=10)

    @model_validator(mode="after")
    def _something_to_frame(self) -> "HighlightRequest":
        interval = self.start is not None and self.end is not None and self.end > self.start
        if not interval and not (self.text and self.text.strip()) and self.chunk_id is None:
            raise ValueError("give a text, an interval of characters (start < end) or a chunk")
        return self


class HighlightRect(BaseModel):
    """A rectangle to frame on the page's screenshot, normalized between 0 and 1 against the page."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float


class HighlightRange(BaseModel):
    """An interval of characters of the page's content: what the text view highlights."""

    start: int
    end: int


class HighlightsOut(BaseModel):
    rects: list[HighlightRect]
    ranges: list[HighlightRange]
    # For a chunk (#353): the pages it is on, in order - what a source modal pages through. Empty otherwise,
    # and for a chunk whose pages are not known.
    pages: list[int] = []
