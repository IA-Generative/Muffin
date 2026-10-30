"""when Muffin took a copied collection over (#462)

Revision ID: c5e8f1a4b6d0
Revises: b4d7e0f3a5c9
Create Date: 2026-11-14 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e8f1a4b6d0"
down_revision: str | Sequence[str] | None = "b4d7e0f3a5c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("collections", sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True))
    # The rebuild of a copied collection's index, whose swap makes Muffin take the collection over.
    op.add_column("index_rebuilds", sa.Column("adopts", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("index_rebuilds", "adopts")
    op.drop_column("collections", "adopted_at")
