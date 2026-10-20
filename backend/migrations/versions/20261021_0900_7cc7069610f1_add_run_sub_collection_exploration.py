"""add run sub-collection exploration state

Revision ID: 7cc7069610f1
Revises: a44d4216a608
Create Date: 2026-10-21 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7cc7069610f1"
down_revision: str | Sequence[str] | None = "a44d4216a608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "runs", sa.Column("unexplored_collection_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("runs", sa.Column("continue_exploration", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "continue_exploration")
    op.drop_column("runs", "unexplored_collection_ids")
