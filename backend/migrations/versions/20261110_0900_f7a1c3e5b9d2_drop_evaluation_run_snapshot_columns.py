"""evaluation runs: drop the dead snapshot and k columns

The chunking/embedding snapshot and k were persisted on every run but never read
back: the UI shows the run's configuration from the results.json artifact's
config_muffin block instead. Drop the columns.

Revision ID: f7a1c3e5b9d2
Revises: e5c7dcb72d4f
Create Date: 2026-11-10 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a1c3e5b9d2"
down_revision: str | Sequence[str] | None = "e5c7dcb72d4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "k",
    "snapshot_chunking_strategy",
    "snapshot_chunk_size",
    "snapshot_chunk_overlap",
    "snapshot_embedding_model",
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("evaluation_runs") as batch:
        for column in _COLUMNS:
            batch.drop_column(column)


def downgrade() -> None:
    """Downgrade schema."""
    # Re-added nullable: the values are gone, and the model no longer reads them.
    with op.batch_alter_table("evaluation_runs") as batch:
        batch.add_column(sa.Column("snapshot_embedding_model", sa.String(), nullable=True))
        batch.add_column(sa.Column("snapshot_chunk_overlap", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("snapshot_chunk_size", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "snapshot_chunking_strategy",
                sa.Enum("PARAGRAPH", "FIXED", "SEMANTIC", "LLM", name="chunking_strategy"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("k", sa.Integer(), nullable=True))
