"""keep every sheet of a tabular file: its analysis, its types, and where its typed copy is (#431)

Revision ID: c9e2f5a8b0d4
Revises: b8d1e4f7a9c3
Create Date: 2026-11-08 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c9e2f5a8b0d4"
down_revision: str | Sequence[str] | None = "b8d1e4f7a9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_tabular_sheets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("sheet_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("header_detected", sa.Boolean(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preview", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("table", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parquet_key", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "sheet_index", name="uq_document_tabular_sheets_document_index"),
    )
    op.create_index(
        op.f("ix_document_tabular_sheets_document_id"), "document_tabular_sheets", ["document_id"], unique=False
    )
    # NULL for a profile computed before the sheets were kept: it has none until the document is indexed again.
    op.add_column("document_tabular_profiles", sa.Column("analysis_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("document_tabular_profiles", "analysis_version")
    op.drop_index(op.f("ix_document_tabular_sheets_document_id"), table_name="document_tabular_sheets")
    op.drop_table("document_tabular_sheets")
