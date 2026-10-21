"""add the source passage of a QA pair

Revision ID: f3a7c9e1b5d2
Revises: e2f6b8d4a0c3
Create Date: 2026-10-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a7c9e1b5d2"
down_revision: str | Sequence[str] | None = "e2f6b8d4a0c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing pairs stay NULL: their passage is found the first time they are shown as a suggestion.
    op.add_column("qa_pairs", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("qa_pairs", sa.Column("source_chunk_id", sa.UUID(), nullable=True))
    op.add_column("qa_pairs", sa.Column("source_excerpt", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_qa_pairs_source_chunk_id_chunks", "qa_pairs", "chunks", ["source_chunk_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_qa_pairs_source_chunk_id_chunks", "qa_pairs", type_="foreignkey")
    op.drop_column("qa_pairs", "source_excerpt")
    op.drop_column("qa_pairs", "source_chunk_id")
    op.drop_column("qa_pairs", "source_page")
