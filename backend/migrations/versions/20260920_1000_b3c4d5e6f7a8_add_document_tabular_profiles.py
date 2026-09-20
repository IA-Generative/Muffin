"""add document_tabular_profiles table

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e8f9
Create Date: 2026-09-20 10:00:00

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create document_tabular_profiles table.

    Stores the DuckDB-computed statistical profile of a tabular document
    (CSV/XLSX/Parquet/JSON) - see issue #69. One-to-one with documents:
    a non-tabular document simply has no row here.
    """
    op.create_table(
        "document_tabular_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("sample_rows", postgresql.JSONB(), nullable=False),
        sa.Column("measures", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("text_columns", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Drop document_tabular_profiles table."""
    op.drop_table("document_tabular_profiles")
