"""habits of use

Revision ID: a2d7f9b4c536
Revises: f1c6e8a3b425
Create Date: 2026-11-01 23:32:57.743779

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a2d7f9b4c536"
down_revision: str | Sequence[str] | None = "f1c6e8a3b425"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("user_memories", sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_memories", "data")
