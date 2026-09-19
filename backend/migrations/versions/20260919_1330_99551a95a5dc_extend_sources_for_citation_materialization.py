"""extend sources for citation materialization

Revision ID: 99551a95a5dc
Revises: 74d4601fff9f
Create Date: 2026-09-19 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99551a95a5dc"
down_revision: str | Sequence[str] | None = "3803fa42d989"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # No server_default needed on the new columns or the now-nullable url: sources has never had
    # a write path (see backend/app/models/source.py), so it's empty in every real deployment.
    op.alter_column("sources", "url", existing_type=sa.String(), nullable=True)
    op.add_column("sources", sa.Column("document_id", sa.UUID(), nullable=True))
    op.add_column("sources", sa.Column("chunk_id", sa.UUID(), nullable=True))
    op.add_column("sources", sa.Column("page_number", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "sources_document_id_fkey", "sources", "documents", ["document_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key("sources_chunk_id_fkey", "sources", "chunks", ["chunk_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("sources_chunk_id_fkey", "sources", type_="foreignkey")
    op.drop_constraint("sources_document_id_fkey", "sources", type_="foreignkey")
    op.drop_column("sources", "page_number")
    op.drop_column("sources", "chunk_id")
    op.drop_column("sources", "document_id")
    op.alter_column("sources", "url", existing_type=sa.String(), nullable=False)
