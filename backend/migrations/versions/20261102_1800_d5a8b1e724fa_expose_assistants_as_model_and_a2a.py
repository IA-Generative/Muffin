"""expose assistants as an OpenAI-compatible model and as an A2A agent (#a2a)

Revision ID: d5a8b1e724fa
Revises: c4f7a0d3e619
Create Date: 2026-11-02 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5a8b1e724fa"
down_revision: str | Sequence[str] | None = "c4f7a0d3e619"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("assistants", sa.Column("expose_as_model", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("assistants", sa.Column("expose_as_a2a", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("assistants", sa.Column("a2a_token_hash", sa.String(length=128), nullable=True))
    op.add_column("assistants", sa.Column("a2a_token_prefix", sa.String(length=32), nullable=True))
    op.add_column(
        "assistants",
        sa.Column("a2a_owner_groups", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("assistants", "a2a_owner_groups")
    op.drop_column("assistants", "a2a_token_prefix")
    op.drop_column("assistants", "a2a_token_hash")
    op.drop_column("assistants", "expose_as_a2a")
    op.drop_column("assistants", "expose_as_model")
