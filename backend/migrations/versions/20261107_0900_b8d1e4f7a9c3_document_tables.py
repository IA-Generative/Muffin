"""keep the tables read on scanned pages: their grid, their Markdown and HTML, where the agent goes to read them (#410)

Revision ID: b8d1e4f7a9c3
Revises: a7c0d3e6f8b2
Create Date: 2026-11-07 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8d1e4f7a9c3"
down_revision: str | Sequence[str] | None = "a7c0d3e6f8b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_tables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_page_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("n_rows", sa.Integer(), nullable=False),
        sa.Column("n_cols", sa.Integer(), nullable=False),
        sa.Column("has_header", sa.Boolean(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cells", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reliable", sa.Boolean(), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["document_page_id"], ["document_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_page_id", "rank", name="uq_document_tables_page_rank"),
    )
    op.create_index(op.f("ix_document_tables_document_page_id"), "document_tables", ["document_page_id"], unique=False)
    # `page_regions.table_id` was left free in #409, for this: a region points at the table read from it.
    op.create_foreign_key(
        "fk_page_regions_table_id", "page_regions", "document_tables", ["table_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_page_regions_table_id", "page_regions", type_="foreignkey")
    op.drop_index(op.f("ix_document_tables_document_page_id"), table_name="document_tables")
    op.drop_table("document_tables")
