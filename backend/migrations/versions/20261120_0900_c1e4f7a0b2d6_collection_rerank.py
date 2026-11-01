"""reranking of a collection's searches, chosen per collection (#511)

Revision ID: c1e4f7a0b2d6
Revises: b0d3e6f9a1c5
Create Date: 2026-11-20 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e4f7a0b2d6"
down_revision: str | Sequence[str] | None = "b0d3e6f9a1c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "collection_settings", sa.Column("rerank_enabled", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("collection_settings", "rerank_enabled")
