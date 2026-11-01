"""the requests to run a tool that changes data, decided by the person (#343)

Revision ID: a5d8e1f4b6c0
Revises: f4b7c0d3e5a9
Create Date: 2026-11-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a5d8e1f4b6c0"
down_revision: str | Sequence[str] | None = "f4b7c0d3e5a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("tool_ref", sa.String(length=160), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("server_name", sa.String(length=100), nullable=True),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_tool_calls_user_id"), "chat_tool_calls", ["user_id"], unique=False)
    op.create_index(op.f("ix_chat_tool_calls_conversation_id"), "chat_tool_calls", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_chat_tool_calls_run_id"), "chat_tool_calls", ["run_id"], unique=False)
    op.create_index(op.f("ix_chat_tool_calls_status"), "chat_tool_calls", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chat_tool_calls")
