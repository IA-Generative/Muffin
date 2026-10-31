import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


class InternalDocumentOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    type: str
    status: str
    storage_key: str | None
    summary: str | None = None
    # SHA-256 of the file (#300) - None until known. What the worker fingerprints the pipeline stages with.
    content_hash: str | None = None


class CollectionDocumentOut(BaseModel):
    """A document of a collection, by name: what a task that samples the collection picks from."""

    id: uuid.UUID
    name: str


class DocumentStatusUpdate(BaseModel):
    status: str
    progress: int | None = None
    summary: str | None = None


class WordBoxIn(BaseModel):
    """A word of a line of the page (#350): its box, normalized between 0 and 1 against the page, and where
    it is in the page's content (None when it could not be found there)."""

    text: str = Field(max_length=500)
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class TextBoxIn(WordBoxIn):
    """A line of the page's text, with its words."""

    text: str = Field(max_length=5000)
    words: list[WordBoxIn] = Field(default_factory=list, max_length=1000)


class RegionIn(BaseModel):
    """A region of the layout of a scanned page (#409): its type, its score, and its box, normalized between 0 and 1
    against the page. Sent in reading order."""

    # Free text rather than a list: a pod newer than this backend may find more kinds of region.
    type: str = Field(min_length=1, max_length=32)
    score: float = Field(ge=0, le=1)
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)
    polygon: list[tuple[float, float]] | None = Field(default=None, max_length=200)
    title_level: int | None = Field(default=None, ge=1, le=6)
    # The description of an image or a table (#411), and the model that wrote it.
    caption: str | None = Field(default=None, max_length=2000)
    caption_model: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _box_and_outline_are_on_the_page(self) -> "RegionIn":
        if self.x_min > self.x_max or self.y_min > self.y_max:
            raise ValueError("a region's minimum cannot be past its maximum")
        if self.polygon and any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in self.polygon):
            raise ValueError("a region's outline must stay between 0 and 1")
        return self


# What a table may hold. A page of a book has a few; a table of a thousand rows is a spreadsheet, not a scan.
MAX_TABLES_PER_PAGE = 100
MAX_TABLE_ROWS = 1000
MAX_TABLE_COLS = 200
MAX_TABLE_CELLS = 20000


class TableCellIn(BaseModel):
    """A cell of a table (#410): from row/col (0-based), spanning row_span rows and col_span columns."""

    row: int = Field(ge=0, lt=MAX_TABLE_ROWS)
    col: int = Field(ge=0, lt=MAX_TABLE_COLS)
    row_span: int = Field(default=1, ge=1, le=MAX_TABLE_ROWS)
    col_span: int = Field(default=1, ge=1, le=MAX_TABLE_COLS)
    text: str = Field(default="", max_length=5000)


class TableIn(BaseModel):
    """A table read on a page (#410): its grid, and that grid written out as Markdown and as HTML. `rank` is its place
    among the tables of the page, from 1, in reading order; `region_position` the region of the page's layout (its
    `position`) it was read from, when it is known."""

    rank: int = Field(ge=1, le=MAX_TABLES_PER_PAGE)
    region_position: int | None = Field(default=None, ge=0)
    n_rows: int = Field(ge=1, le=MAX_TABLE_ROWS)
    n_cols: int = Field(ge=1, le=MAX_TABLE_COLS)
    has_header: bool = False
    headers: list[str] | None = Field(default=None, max_length=MAX_TABLE_COLS)
    cells: list[TableCellIn] = Field(default_factory=list, max_length=MAX_TABLE_CELLS)
    markdown: str = Field(max_length=1_000_000)
    html: str = Field(max_length=2_000_000)
    score: float = Field(ge=0, le=1)
    # False when the structure is doubtful: kept, and said so.
    reliable: bool = True
    model_version: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def _cells_are_in_the_grid(self) -> "TableIn":
        for cell in self.cells:
            if cell.row + cell.row_span > self.n_rows or cell.col + cell.col_span > self.n_cols:
                raise ValueError(f"the cell ({cell.row}, {cell.col}) goes out of the table")
        return self


class DocumentPageCreate(BaseModel):
    page_number: int
    content: str
    screenshot: str | None = None
    # The page's lines and words with their boxes (#350). None: not sent, what the page has is kept;
    # empty: the page has none (a page written again without them loses them).
    text_boxes: list[TextBoxIn] | None = Field(default=None, max_length=5000)
    # The regions of the page's layout, in reading order (#409). Same rule as the lines: None, what the page has is
    # kept; empty, the page has none (a page read again by something that finds no layout loses the old ones).
    regions: list[RegionIn] | None = Field(default=None, max_length=500)
    # The tables read on the page (#410). Same rule again: None, what the page has is kept; empty, it has none.
    tables: list[TableIn] | None = Field(default=None, max_length=MAX_TABLES_PER_PAGE)

    @model_validator(mode="after")
    def _one_table_per_rank(self) -> "DocumentPageCreate":
        ranks = [table.rank for table in self.tables or []]
        if len(ranks) != len(set(ranks)):
            raise ValueError("two tables of a page cannot share a rank")
        return self


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
    # The model the worker made the vector with - redone with the index's own model when it differs
    # (a vector computed just before the index was rebuilt with a new one, #12).
    embedding_model: str | None = None
