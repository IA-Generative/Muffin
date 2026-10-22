"""keep the documents of an import waiting for their turn to be extracted (#335)

Revision ID: e8a2c6b0d4f7
Revises: d7f1b5a9c3e6
Create Date: 2026-10-29 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a2c6b0d4f7"
down_revision: str | Sequence[str] | None = "d7f1b5a9c3e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_documents",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_id"], ["collection_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(op.f("ix_import_documents_import_id"), "import_documents", ["import_id"], unique=False)
    op.create_index(
        "ix_import_documents_waiting", "import_documents", ["import_id", "created_at", "document_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_import_documents_waiting", table_name="import_documents")
    op.drop_index(op.f("ix_import_documents_import_id"), table_name="import_documents")
    op.drop_table("import_documents")
