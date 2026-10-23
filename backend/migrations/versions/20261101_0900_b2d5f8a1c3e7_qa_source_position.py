"""where the passage a question-answer pair comes from is in its page (#351)

Revision ID: b2d5f8a1c3e7
Revises: a1c4e7b9d2f6
Create Date: 2026-11-01 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d5f8a1c3e7"
down_revision: str | Sequence[str] | None = "a1c4e7b9d2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("qa_pairs", sa.Column("source_start", sa.Integer(), nullable=True))
    op.add_column("qa_pairs", sa.Column("source_end", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("qa_pairs", "source_end")
    op.drop_column("qa_pairs", "source_start")
