"""learned memory

Revision ID: f1c6e8a3b425
Revises: e9b5d7f2a314
Create Date: 2026-11-01 23:19:23.062722

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1c6e8a3b425"
down_revision: str | Sequence[str] | None = "e9b5d7f2a314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("user_memory_settings", sa.Column("learning_from", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_memory_settings", "learning_from")
