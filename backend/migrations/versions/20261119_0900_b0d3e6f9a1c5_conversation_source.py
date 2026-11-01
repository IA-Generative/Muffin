"""what made a conversation, for those a program makes (#513)

Revision ID: b0d3e6f9a1c5
Revises: a9c2d5e8f0b4
Create Date: 2026-11-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0d3e6f9a1c5"
down_revision: str | Sequence[str] | None = "a9c2d5e8f0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("conversations", sa.Column("source", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_conversations_source"), "conversations", ["source"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_conversations_source"), table_name="conversations")
    op.drop_column("conversations", "source")
