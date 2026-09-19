"""add discussion scores and task conversation scoping

Revision ID: 5e9f8378ec61
Revises: 516194aecb9b
Create Date: 2026-09-19 15:30:48.422132

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5e9f8378ec61"
down_revision: str | Sequence[str] | None = "516194aecb9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "discussion_scores",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("llm_model", sa.String(), nullable=False),
        sa.Column("coherent", sa.Boolean(), nullable=False),
        sa.Column("coherence_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_usage_score", sa.Float(), nullable=False),
        sa.Column("context_usage_issues", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_discussion_scores_conversation_id"), "discussion_scores", ["conversation_id"], unique=False
    )
    # No server_default needed: tasks already has rows in a real deployment, but this column is
    # nullable (see app/models/task.py - not every task type relates to a conversation).
    op.add_column("tasks", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "tasks_conversation_id_fkey", "tasks", "conversations", ["conversation_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("tasks_conversation_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "conversation_id")
    op.drop_index(op.f("ix_discussion_scores_conversation_id"), table_name="discussion_scores")
    op.drop_table("discussion_scores")
