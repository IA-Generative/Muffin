"""add value polarity to feedbacks

Revision ID: 3803fa42d989
Revises: 74d4601fff9f
Create Date: 2026-09-19 12:48:21.891288

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3803fa42d989"
down_revision: str | Sequence[str] | None = "74d4601fff9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

feedback_value_enum = sa.Enum("UP", "DOWN", name="feedback_value")


def upgrade() -> None:
    """Upgrade schema."""
    # New enum types aren't auto-created by ADD COLUMN the way CREATE TABLE would - must create
    # it explicitly first. No server_default needed: feedbacks has never had a write path (see
    # backend/app/models/feedback.py), so it's empty in every real deployment.
    feedback_value_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("feedbacks", sa.Column("value", feedback_value_enum, nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("feedbacks", "value")
    feedback_value_enum.drop(op.get_bind(), checkfirst=True)
