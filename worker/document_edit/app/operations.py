"""Typed edit operations on a document (#168). What the editing agent produces and what the
applier executes - a closed vocabulary rather than free-form text, so that every change is
checkable, can be shown to the user as a list, and never touches anything it doesn't name.

A target is designated by its section's heading text plus a 1-based index, not by an internal
identifier: that stays valid if the document was edited by hand since it was read, and it is
something a language model can produce from the document's outline."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class SectionRef(BaseModel):
    """A section: the elements between a heading and the next heading (of any level). `heading`
    None is the part of the document before its first heading."""

    heading: str | None = None
    # Which one, when several headings have the same text (1-based, document order).
    occurrence: int = Field(default=1, ge=1)


class TableRef(BaseModel):
    section: SectionRef
    # The nth table of that section (1-based).
    index: int = Field(default=1, ge=1)


class ReplaceParagraph(BaseModel):
    op: Literal["replace_paragraph"] = "replace_paragraph"
    section: SectionRef
    # The nth paragraph of the section (1-based) - list items and table cells aren't counted.
    paragraph: int = Field(ge=1)
    text: str


class InsertParagraph(BaseModel):
    op: Literal["insert_paragraph"] = "insert_paragraph"
    section: SectionRef
    # Insert after this paragraph: 0 right under the heading, None at the end of the section.
    after_paragraph: int | None = Field(default=None, ge=0)
    text: str


class DeleteParagraph(BaseModel):
    op: Literal["delete_paragraph"] = "delete_paragraph"
    section: SectionRef
    paragraph: int = Field(ge=1)


class InsertSection(BaseModel):
    op: Literal["insert_section"] = "insert_section"
    # Insert after this section and its subsections; None at the end of the document.
    after: SectionRef | None = None
    level: int = Field(ge=1, le=6)
    title: str = Field(min_length=1)
    paragraphs: list[str] = []


class SetCell(BaseModel):
    op: Literal["set_cell"] = "set_cell"
    table: TableRef
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    text: str


class InsertRow(BaseModel):
    op: Literal["insert_row"] = "insert_row"
    table: TableRef
    # Insert after this row: 0 at the very top, None at the bottom.
    after_row: int | None = Field(default=None, ge=0)
    # One text per column; a shorter list leaves the remaining cells empty.
    values: list[str] = []


class DeleteRow(BaseModel):
    op: Literal["delete_row"] = "delete_row"
    table: TableRef
    row: int = Field(ge=1)


class InsertColumn(BaseModel):
    op: Literal["insert_column"] = "insert_column"
    table: TableRef
    # Insert after this column: 0 at the far left, None at the far right.
    after_column: int | None = Field(default=None, ge=0)
    # One text per row (header first); a shorter list leaves the remaining cells empty.
    values: list[str] = []


class DeleteColumn(BaseModel):
    op: Literal["delete_column"] = "delete_column"
    table: TableRef
    column: int = Field(ge=1)


class InsertTable(BaseModel):
    op: Literal["insert_table"] = "insert_table"
    section: SectionRef
    # Same convention as InsertParagraph.after_paragraph.
    after_paragraph: int | None = Field(default=None, ge=0)
    # At least one row; every row must have the same number of cells. The first row is the header.
    rows: list[list[str]] = Field(min_length=1)


Operation = Annotated[
    ReplaceParagraph
    | InsertParagraph
    | DeleteParagraph
    | InsertSection
    | SetCell
    | InsertRow
    | DeleteRow
    | InsertColumn
    | DeleteColumn
    | InsertTable,
    Field(discriminator="op"),
]

# Validates a whole list of operations as an agent (or a test) hands them over.
OperationList = TypeAdapter(list[Operation])
