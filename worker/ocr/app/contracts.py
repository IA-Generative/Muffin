"""What the OCR pods exchange: the regions of a page, the text read in them, the structure of a table.

Each pod is its own image, so this module only depends on pydantic - it is copied as it is into the image of
every pod that needs it. Boxes are **normalized between 0 and 1** against the page, as the page's text boxes are
(app/text_boxes.py), so a region lands on the page's screenshot whatever the scale it was rendered at.

Versioning: a field added to a contract does not change SCHEMA_VERSION - readers ignore what they do not know, so a
pod can be updated before the others. SCHEMA_VERSION is raised only for a change that breaks a reader (a field
removed or given another meaning); a reader refuses a payload of a version newer than its own."""

import enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class RegionType(enum.StrEnum):
    TEXT = "text"
    TITLE = "title"
    LIST = "list"
    CAPTION = "caption"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"
    LOGO = "logo"
    STAMP = "stamp"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    OTHER = "other"

    @property
    def is_text(self) -> bool:
        """Read by the OCR, and in the page's markdown."""
        return self in _TEXT_TYPES

    @property
    def is_kept_as_crop(self) -> bool:
        """Not text, but its crop is kept in S3 (#409)."""
        return self in _CROP_TYPES

    @property
    def is_dropped(self) -> bool:
        """Neither in the markdown nor kept anywhere: the running headers and footers of a page."""
        return self in _DROPPED_TYPES


_TEXT_TYPES = frozenset({RegionType.TEXT, RegionType.TITLE, RegionType.LIST, RegionType.CAPTION})
_CROP_TYPES = frozenset({RegionType.TABLE, RegionType.IMAGE, RegionType.FORMULA, RegionType.LOGO, RegionType.STAMP})
_DROPPED_TYPES = frozenset({RegionType.HEADER, RegionType.FOOTER, RegionType.PAGE_NUMBER})


class _Contract(BaseModel):
    # Unknown fields are ignored, not refused (see the module's docstring).
    model_config = ConfigDict(extra="ignore")

    schema_version: int = SCHEMA_VERSION

    @field_validator("schema_version")
    @classmethod
    def _known_version(cls, version: int) -> int:
        if version > SCHEMA_VERSION:
            raise ValueError(f"schema version {version} is newer than the {SCHEMA_VERSION} this reader knows")
        return version


class _Plain(BaseModel):
    """A part of a contract: no version of its own."""

    model_config = ConfigDict(extra="ignore")


class Box(_Plain):
    x_min: Unit
    y_min: Unit
    x_max: Unit
    y_max: Unit

    @model_validator(mode="after")
    def _ordered(self) -> "Box":
        if self.x_min > self.x_max or self.y_min > self.y_max:
            raise ValueError("a box's minimum cannot be past its maximum")
        return self


class Region(_Plain):
    type: RegionType
    score: Unit
    # 0 is read first. Unique within a page.
    reading_order: int = Field(ge=0)
    box: Box
    polygon: list[tuple[Unit, Unit]] | None = None
    # A title only: 1 for the title of the document, 2 for a section's. None when the model does not tell.
    title_level: int | None = Field(default=None, ge=1, le=6)


class PageLayout(_Contract):
    """What the layout pod finds on a page: its regions, in reading order. A page without any region is a valid
    result - the caller then falls back on the parser's own OCR."""

    document_id: str
    page_number: int = Field(ge=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    regions: list[Region] = Field(default_factory=list)
    model_version: str

    @model_validator(mode="after")
    def _in_reading_order(self) -> "PageLayout":
        orders = [region.reading_order for region in self.regions]
        if len(set(orders)) != len(orders):
            raise ValueError("two regions of a page cannot share a reading order")
        if orders != sorted(orders):
            raise ValueError("the regions of a page come in reading order")
        return self


class OcrWord(_Plain):
    text: str
    score: Unit
    box: Box


class OcrLine(_Plain):
    text: str
    score: Unit
    box: Box
    # Optional: the pod may not be able to place the words of a line.
    words: list[OcrWord] = Field(default_factory=list)


class RegionText(_Plain):
    # The reading_order of the region of the PageLayout it was read in.
    region_order: int = Field(ge=0)
    lines: list[OcrLine] = Field(default_factory=list)


class PageText(_Contract):
    """What the ocr pod reads in the text regions of a page."""

    document_id: str
    page_number: int = Field(ge=1)
    regions: list[RegionText] = Field(default_factory=list)
    model_version: str


class TableCell(_Plain):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str = ""
    box: Box | None = None


class TableStructure(_Plain):
    # The reading_order of the table's region.
    region_order: int = Field(ge=0)
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: list[TableCell] = Field(default_factory=list)
    has_header: bool = False
    score: Unit

    @model_validator(mode="after")
    def _cells_inside(self) -> "TableStructure":
        for cell in self.cells:
            if cell.row + cell.row_span > self.n_rows or cell.col + cell.col_span > self.n_cols:
                raise ValueError(f"the cell ({cell.row}, {cell.col}) goes out of the table")
        return self


class PageTables(_Contract):
    """What the table pod reads in the table regions of a page."""

    document_id: str
    page_number: int = Field(ge=1)
    tables: list[TableStructure] = Field(default_factory=list)
    model_version: str
