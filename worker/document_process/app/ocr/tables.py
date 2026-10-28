"""The tables the table pod read on a scanned page (#410), written out for what keeps them.

The page's markdown holds only a **marker** for each table:

    [Tableau <document>/p3/t1 — colonnes : Année | Dossiers | Délai — 12 lignes]

its headers and its size are in the text, so they are indexed and found; its content is not - it is kept apart (the
backend's `document_tables`) and the agent goes to read it when a passage says a table is there. What is kept is the
grid, that grid as Markdown, and as HTML: a cell that spans rows or columns cannot be said in Markdown, so the HTML is
the exact one and the Markdown the grid with such a cell's text in its first place."""

import html as html_lib
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.ocr.contracts import PageLayout, PageTables, TableStructure
from app.ocr.regions import MAX_REGIONS

# What the backend accepts of a table (schemas/internal_document.py).
MAX_CELL_CHARS = 2000
MAX_MARKDOWN_CHARS = 900_000
MAX_HTML_CHARS = 1_800_000
# The headers in the marker: a page whose tables have a hundred columns must not become its markers.
MARKER_HEADERS_CHARS = 240


@dataclass
class RenderedTable:
    """A table of a page, ready for the marker in the page's text and for the backend."""

    rank: int
    region_order: int
    n_rows: int
    n_cols: int
    has_header: bool
    headers: list[str] | None
    cells: list[dict[str, Any]]
    markdown: str
    html: str
    score: float
    reliable: bool
    model_version: str
    marker: str

    def payload(self, layout: PageLayout) -> dict[str, Any]:
        """The table as the backend's `TableIn` takes it, tied to its region by the region's place in the layout it is
        sent with (`regions_of`)."""
        position = next(
            (
                index
                for index, region in enumerate(layout.regions[:MAX_REGIONS])
                if region.reading_order == self.region_order
            ),
            None,
        )
        return {
            "rank": self.rank,
            "region_position": position,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "has_header": self.has_header,
            "headers": self.headers,
            "cells": self.cells,
            "markdown": self.markdown,
            "html": self.html,
            "score": self.score,
            "reliable": self.reliable,
            "model_version": self.model_version,
        }


def _text(value: str) -> str:
    """A cell's text on one line, within what the backend keeps."""
    return " ".join(value.split())[:MAX_CELL_CHARS]


def header_rows(table: TableStructure) -> int:
    """How many rows at the top are the header: one, or two when the first has a cell over several columns (a title
    above the names of the columns it groups)."""
    if not table.has_header:
        return 0
    first = [cell for cell in table.cells if cell.row == 0]
    return 2 if table.n_rows > 2 and any(cell.col_span > 1 for cell in first) else 1


def column_headers(table: TableStructure, rows: int) -> list[str]:
    """The header of each column: what the header rows say over it, from the top - "Résultats / Réalisé"."""
    headers = []
    for column in range(table.n_cols):
        parts: list[str] = []
        for cell in sorted(table.cells, key=lambda c: (c.row, c.col)):
            if cell.row < rows and cell.col <= column < cell.col + cell.col_span:
                text = _text(cell.text)
                if text and text not in parts:
                    parts.append(text)
        headers.append(" / ".join(parts))
    return headers


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def to_markdown(table: TableStructure) -> str:
    """The grid as a Markdown table. A table with no header gets an empty one, which Markdown requires; a cell that
    spans several has its text in its first place and the others empty (the HTML is the exact one)."""
    grid = [["" for _ in range(table.n_cols)] for _ in range(table.n_rows)]
    for cell in table.cells:
        grid[cell.row][cell.col] = _text(cell.text)

    def row(texts: list[str]) -> str:
        return "| " + " | ".join(_escape(text) for text in texts) + " |"

    if table.has_header:
        header, body = grid[0], grid[1:]
    else:
        header, body = ["" for _ in range(table.n_cols)], grid
    return "\n".join([row(header), "| " + " | ".join("---" for _ in range(table.n_cols)) + " |", *map(row, body)])


def to_html(table: TableStructure) -> str:
    """The grid as an HTML table, spans said as they are. The first row is the head when it is a header."""

    def cell_html(cell, tag: str) -> str:
        spans = ""
        if cell.row_span > 1:
            spans += f' rowspan="{cell.row_span}"'
        if cell.col_span > 1:
            spans += f' colspan="{cell.col_span}"'
        return f"<{tag}{spans}>{html_lib.escape(_text(cell.text))}</{tag}>"

    rows: dict[int, list] = {}
    for cell in sorted(table.cells, key=lambda c: (c.row, c.col)):
        rows.setdefault(cell.row, []).append(cell)
    lines = ["<table>"]
    for index in range(table.n_rows):
        in_header = table.has_header and index == 0
        if in_header:
            lines.append("<thead>")
        elif table.has_header and index == 1:
            lines.append("<tbody>")
        elif not table.has_header and index == 0:
            lines.append("<tbody>")
        tag = "th" if in_header else "td"
        lines.append("<tr>" + "".join(cell_html(cell, tag) for cell in rows.get(index, [])) + "</tr>")
        if in_header:
            lines.append("</thead>")
    if table.n_rows > (1 if table.has_header else 0):
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def marker(
    document_id: str, page_number: int, rank: int, table: TableStructure, headers: list[str], rows: int, reliable: bool
) -> str:
    """What the page's text says of the table: where it is, what its columns are, how long it is."""
    identifier = f"{document_id}/p{page_number}/t{rank}"
    data_rows = table.n_rows - rows
    length = f"{data_rows} ligne" + ("s" if data_rows != 1 else "")
    if rows and any(headers):
        named = " | ".join(text for text in headers if text)
        if len(named) > MARKER_HEADERS_CHARS:
            named = named[:MARKER_HEADERS_CHARS].rstrip() + "…"
        columns = f"colonnes : {named.replace(']', ')').replace('[', '(')}"
    else:
        columns = f"{table.n_cols} colonne" + ("s" if table.n_cols != 1 else "")
    doubt = " — structure douteuse" if not reliable else ""
    return f"[Tableau {identifier} — {columns} — {length}{doubt}]"


def render_page(layout: PageLayout, page_tables: PageTables, document_id: str, page_number: int) -> list[RenderedTable]:
    """The tables of a page, in reading order, each with its rank on the page (from 1). Refuses a page where a table the
    layout found was not read: its content would be in the page nowhere."""
    table_regions = sorted(region.reading_order for region in layout.regions if region.type.value == "table")
    read = {table.region_order: table for table in page_tables.tables}
    missing = [order for order in table_regions if order not in read]
    if missing:
        raise ValueError(f"the table pod read no table in region(s) {missing}")
    rendered = []
    for rank, order in enumerate(table_regions, start=1):
        table = read[order]
        rows = header_rows(table)
        headers = column_headers(table, rows) if rows else None
        reliable = table.score >= settings.OCR_TABLE_MIN_SCORE
        markdown, html = to_markdown(table), to_html(table)
        if len(markdown) > MAX_MARKDOWN_CHARS or len(html) > MAX_HTML_CHARS:
            raise ValueError(f"the table of region {order} is too big to be kept")
        rendered.append(
            RenderedTable(
                rank=rank,
                region_order=order,
                n_rows=table.n_rows,
                n_cols=table.n_cols,
                has_header=table.has_header,
                headers=headers,
                cells=[
                    {
                        "row": cell.row,
                        "col": cell.col,
                        "row_span": cell.row_span,
                        "col_span": cell.col_span,
                        "text": _text(cell.text),
                    }
                    for cell in table.cells
                ],
                markdown=markdown,
                html=html,
                score=table.score,
                reliable=reliable,
                model_version=page_tables.model_version,
                marker=marker(document_id, page_number, rank, table, headers or [], rows, reliable),
            )
        )
    return rendered
