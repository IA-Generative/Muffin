"""add latency_ms and token columns to messages

Revision ID: a1b2c3d4e8f9
Revises: 45e67f238e78
Create Date: 2026-09-19 22:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e8f9"
down_revision = "45e67f238e78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add latency_ms, prompt_tokens, and completion_tokens to messages.

    All nullable: only set on ASSISTANT messages produced by the agent worker
    (the run that generated them). Existing rows and USER messages stay NULL.
    Used by the quality dashboard to compute average response latency and
    estimated cost (0.75 × total tokens).
    """
    op.add_column(
        "messages",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "completion_tokens")
    op.drop_column("messages", "prompt_tokens")
    op.drop_column("messages", "latency_ms")
