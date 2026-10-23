"""keep where each entity is in the pages, and the sentence behind each relation (#352)

Revision ID: c3e6a9b2d4f8
Revises: b2d5f8a1c3e7
Create Date: 2026-11-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e6a9b2d4f8"
down_revision: str | Sequence[str] | None = "b2d5f8a1c3e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("window_key", sa.String(), server_default="", nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_entity_mentions_entity_id"), "entity_mentions", ["entity_id"], unique=False)
    op.create_index(
        "ix_entity_mentions_document_window", "entity_mentions", ["document_id", "window_key"], unique=False
    )
    op.add_column("relations", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("relations", sa.Column("source_excerpt", sa.Text(), nullable=True))
    op.add_column("relations", sa.Column("source_start", sa.Integer(), nullable=True))
    op.add_column("relations", sa.Column("source_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("source_end", "source_start", "source_excerpt", "source_page"):
        op.drop_column("relations", column)
    op.drop_index("ix_entity_mentions_document_window", table_name="entity_mentions")
    op.drop_index(op.f("ix_entity_mentions_entity_id"), table_name="entity_mentions")
    op.drop_table("entity_mentions")
