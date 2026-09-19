"""add grounding result to runs

Revision ID: 74d4601fff9f
Revises: 9c08ea420680
Create Date: 2026-09-19 09:27:21.521283

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "74d4601fff9f"
down_revision: str | Sequence[str] | None = "9c08ea420680"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("runs", sa.Column("grounding_valid", sa.Boolean(), nullable=True))
    op.add_column(
        "runs", sa.Column("grounding_unsupported_claims", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("runs", sa.Column("grounding_research_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "grounding_research_count")
    op.drop_column("runs", "grounding_unsupported_claims")
    op.drop_column("runs", "grounding_valid")
