"""make the pipeline's writes idempotent: one page and one chunk per position, replaceable QA and entity runs

Revision ID: b5d9f3a7c1e4
Revises: a4c8e2f6b0d3
Create Date: 2026-10-26 09:00:00.000000

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5d9f3a7c1e4"
down_revision: str | Sequence[str] | None = "a4c8e2f6b0d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def _remove_duplicates(table: str, key_column: str) -> int:
    """Keeps one row per (document, position): the one written last, which is the latest run of the
    pipeline. What a task run twice (#299) left behind is a full second copy of each row."""
    result = op.get_bind().execute(
        sa.text(
            f"DELETE FROM {table} older USING {table} newer "  # noqa: S608 - fixed names, not user input
            f"WHERE older.document_id = newer.document_id AND older.{key_column} = newer.{key_column} "
            "AND older.ctid < newer.ctid"
        )
    )
    return result.rowcount


def upgrade() -> None:
    """Upgrade schema."""
    # What exists is cleaned before the constraints go on, or they could not. Chunks removed here
    # leave a vector in Meilisearch under their id: search resolves ids against PostgreSQL, so an
    # orphan is never returned (same as after a failed cleanup elsewhere), and the next reprocess of
    # the document removes it. Duplicated QA pairs, entities and relations cannot be told apart from
    # legitimate ones (the model words each run differently), so they are left.
    pages = _remove_duplicates("document_pages", "page_number")
    chunks = _remove_duplicates("chunks", '"index"')
    logger.info("Removed %d duplicated page(s) and %d duplicated chunk(s)", pages, chunks)
    op.create_unique_constraint("uq_document_pages_document_page", "document_pages", ["document_id", "page_number"])
    op.create_unique_constraint("uq_chunks_document_index", "chunks", ["document_id", "index"])

    op.add_column("qa_pairs", sa.Column("generation_key", sa.String(), nullable=True))
    op.add_column("relations", sa.Column("window_key", sa.String(), nullable=True))

    op.add_column("entity_documents", sa.Column("window_key", sa.String(), nullable=False, server_default=""))
    op.drop_constraint("entity_documents_pkey", "entity_documents", type_="primary")
    op.create_primary_key("entity_documents_pkey", "entity_documents", ["entity_id", "document_id", "window_key"])


def downgrade() -> None:
    """Downgrade schema."""
    # One row per (entity, document) again: the windows' mentions are added up.
    op.execute(
        "CREATE TEMPORARY TABLE _entity_documents AS "
        "SELECT entity_id, document_id, SUM(mentions)::integer AS mentions "
        "FROM entity_documents GROUP BY entity_id, document_id"
    )
    op.execute("DELETE FROM entity_documents")
    op.execute(
        "INSERT INTO entity_documents (entity_id, document_id, window_key, mentions) "
        "SELECT entity_id, document_id, '', mentions FROM _entity_documents"
    )
    op.drop_constraint("entity_documents_pkey", "entity_documents", type_="primary")
    op.drop_column("entity_documents", "window_key")
    op.create_primary_key("entity_documents_pkey", "entity_documents", ["entity_id", "document_id"])

    op.drop_column("relations", "window_key")
    op.drop_column("qa_pairs", "generation_key")
    op.drop_constraint("uq_chunks_document_index", "chunks", type_="unique")
    op.drop_constraint("uq_document_pages_document_page", "document_pages", type_="unique")
