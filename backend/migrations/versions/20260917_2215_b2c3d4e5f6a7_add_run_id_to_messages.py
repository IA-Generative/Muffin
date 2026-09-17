"""add run_id to messages

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-17 22:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("run_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_messages_run_id"), "messages", ["run_id"], unique=False)
    op.create_foreign_key("messages_run_id_fkey", "messages", "runs", ["run_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("messages_run_id_fkey", "messages", type_="foreignkey")
    op.drop_index(op.f("ix_messages_run_id"), table_name="messages")
    op.drop_column("messages", "run_id")
