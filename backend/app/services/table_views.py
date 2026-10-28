"""A table read on a scanned page (#410), as the API gives it - to the user and to the agent alike."""

import uuid

from app.models.document import DocumentTable
from app.schemas.document import TableCellOut, TableOut, TableSummaryOut


def table_id(document_id: uuid.UUID, page_number: int, rank: int) -> str:
    """What the page's text says in its `[Tableau ...]` marker: the table's place, which does not change when the
    page is read again."""
    return f"{document_id}/p{page_number}/t{rank}"


def table_summary(document_id: uuid.UUID, table: DocumentTable, page_number: int) -> TableSummaryOut:
    return TableSummaryOut(
        table_id=table_id(document_id, page_number, table.rank),
        page_number=page_number,
        rank=table.rank,
        n_rows=table.n_rows,
        n_cols=table.n_cols,
        has_header=table.has_header,
        headers=table.headers,
        reliable=table.reliable,
        score=table.score,
    )


def table_out(document_id: uuid.UUID, table: DocumentTable, page_number: int) -> TableOut:
    return TableOut(
        **table_summary(document_id, table, page_number).model_dump(),
        cells=[TableCellOut(**cell) for cell in table.cells],
        markdown=table.markdown,
        html=table.html,
        model_version=table.model_version,
    )
