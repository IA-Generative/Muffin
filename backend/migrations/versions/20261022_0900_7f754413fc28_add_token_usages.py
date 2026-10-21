"""add token usages and user profiles

Revision ID: 7f754413fc28
Revises: e59419ac9e72
Create Date: 2026-10-22 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f754413fc28"
down_revision: str | Sequence[str] | None = "e59419ac9e72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "token_usages",
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("kind", sa.Enum("CHAT", "EMBEDDING", name="token_usage_kind"), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("collection_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_token_usages_user_id"), "token_usages", ["user_id"], unique=False)
    op.create_index(op.f("ix_token_usages_created_at"), "token_usages", ["created_at"], unique=False)
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("display", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_token_usages_created_at"), table_name="token_usages")
    op.drop_index(op.f("ix_token_usages_user_id"), table_name="token_usages")
    op.drop_table("token_usages")
    sa.Enum(name="token_usage_kind").drop(op.get_bind(), checkfirst=True)
