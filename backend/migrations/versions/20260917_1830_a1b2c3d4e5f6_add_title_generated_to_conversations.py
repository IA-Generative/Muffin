"""add title_generated to conversations

Revision ID: a1b2c3d4e5f6
Revises: 3632c0e81a2a
Create Date: 2026-09-17 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "3632c0e81a2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default: this column is NOT NULL and the table already has rows.
    op.add_column(
        "conversations", sa.Column("title_generated", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("conversations", "title_generated")
