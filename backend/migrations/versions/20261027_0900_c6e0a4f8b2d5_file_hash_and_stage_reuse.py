"""index the documents' file hash, and record the pipeline stages for reuse across documents

Revision ID: c6e0a4f8b2d5
Revises: b5d9f3a7c1e4
Create Date: 2026-10-27 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c6e0a4f8b2d5"
down_revision: str | Sequence[str] | None = "b5d9f3a7c1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Looked up at every upload, to tell that a file is already in the collection (#300).
    op.create_index(op.f("ix_documents_content_hash"), "documents", ["content_hash"], unique=False)
    op.create_table(
        "document_stages",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("done", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("document_id", "stage"),
    )
    # The lookup of a source: a complete stage of this fingerprint.
    op.create_index(
        "ix_document_stages_lookup",
        "document_stages",
        ["stage", "fingerprint"],
        postgresql_where=sa.text("completed_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_document_stages_lookup", table_name="document_stages")
    op.drop_table("document_stages")
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
