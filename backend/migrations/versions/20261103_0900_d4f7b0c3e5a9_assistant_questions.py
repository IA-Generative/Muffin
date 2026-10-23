"""questions with options asked by the assistant, and their answers (#344)

Revision ID: d4f7b0c3e5a9
Revises: c3e6a9b2d4f8
Create Date: 2026-11-03 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4f7b0c3e5a9"
down_revision: str | Sequence[str] | None = "c3e6a9b2d4f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("messages", sa.Column("questions_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("runs", sa.Column("interactive", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "interactive")
    op.drop_column("messages", "questions_answer")
    op.drop_column("messages", "questions")
