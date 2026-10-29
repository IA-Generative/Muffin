"""the engine that describes the images and tables of scanned pages (#411)

Revision ID: e1a4b7c0d2f6
Revises: d0f3a6b9c1e5
Create Date: 2026-11-10 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a4b7c0d2f6"
down_revision: str | Sequence[str] | None = "d0f3a6b9c1e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "collection_settings",
        sa.Column("caption_engine", sa.String(length=16), server_default="local", nullable=False),
    )
    op.add_column("collection_settings", sa.Column("caption_model", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("collection_settings", "caption_model")
    op.drop_column("collection_settings", "caption_engine")
