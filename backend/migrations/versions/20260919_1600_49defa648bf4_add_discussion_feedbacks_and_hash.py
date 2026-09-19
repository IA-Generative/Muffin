"""add discussion feedbacks and content_hash on discussion scores

Revision ID: 49defa648bf4
Revises: 5e9f8378ec61
Create Date: 2026-09-19 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "49defa648bf4"
down_revision: str | Sequence[str] | None = "5e9f8378ec61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- content_hash on discussion_scores ---
    op.add_column(
        "discussion_scores",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_discussion_scores_conv_hash_model",
        "discussion_scores",
        ["conversation_id", "content_hash", "llm_model"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )

    # --- discussion_feedbacks table ---
    op.create_table(
        "discussion_feedbacks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("coherent", sa.Boolean(), nullable=False),
        sa.Column("context_usage_score", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_discussion_feedbacks_conversation_id"),
        "discussion_feedbacks",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discussion_feedbacks_user_id"),
        "discussion_feedbacks",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_discussion_feedbacks_user_id"), table_name="discussion_feedbacks")
    op.drop_index(
        op.f("ix_discussion_feedbacks_conversation_id"),
        table_name="discussion_feedbacks",
    )
    op.drop_table("discussion_feedbacks")
    op.drop_index("uq_discussion_scores_conv_hash_model", table_name="discussion_scores")
    op.drop_column("discussion_scores", "content_hash")
