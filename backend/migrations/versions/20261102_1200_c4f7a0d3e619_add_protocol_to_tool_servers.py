"""add protocol to tool servers: mcp (several tools) or a2a (one agent, #a2a)

Revision ID: c4f7a0d3e619
Revises: b3e8a1c5d647
Create Date: 2026-11-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f7a0d3e619"
down_revision: str | Sequence[str] | None = "b3e8a1c5d647"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tool_servers", sa.Column("protocol", sa.String(length=8), server_default="mcp", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tool_servers", "protocol")
