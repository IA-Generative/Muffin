"""add blue/green index rebuilds

Revision ID: e2f6b8d4a0c3
Revises: d1e5a7c3f9b2
Create Date: 2026-10-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f6b8d4a0c3"
down_revision: str | Sequence[str] | None = "d1e5a7c3f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("BUILDING", "SWAPPED", "FINALIZED", "ROLLED_BACK", "FAILED")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("collection_settings", sa.Column("index_embedding_model", sa.String(), nullable=True))
    # A collection whose model was changed but never reindexed: its index still holds the vectors
    # of a model this column can't know any more. Left None - the rebuild the owner starts fixes it.
    op.create_table(
        "index_rebuilds",
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Enum(*_STATUSES, name="index_rebuild_status"), nullable=False),
        sa.Column("target_model", sa.String(), nullable=False),
        sa.Column("previous_model", sa.String(), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("done_points", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("swapped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_index_rebuilds_collection_id"), "index_rebuilds", ["collection_id"], unique=False)
    # The per-collection lock: one building or swapped rebuild at most, enforced by the database too.
    op.create_index(
        "uq_index_rebuilds_one_active",
        "index_rebuilds",
        ["collection_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('BUILDING', 'SWAPPED')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_index_rebuilds_one_active", table_name="index_rebuilds")
    op.drop_index(op.f("ix_index_rebuilds_collection_id"), table_name="index_rebuilds")
    op.drop_table("index_rebuilds")
    sa.Enum(name="index_rebuild_status").drop(op.get_bind(), checkfirst=True)
    op.drop_column("collection_settings", "index_embedding_model")
