"""tools the chat may call: servers added by users, their tools, the journal of calls (#343)

Revision ID: f4b7c0d3e5a9
Revises: e3a6b9c2d4f8
Create Date: 2026-11-23 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f4b7c0d3e5a9"
down_revision: str | Sequence[str] | None = "e3a6b9c2d4f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tool_servers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("auth_mode", sa.String(length=8), server_default="none", nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=8), server_default="private", nullable=False),
        sa.Column("group_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_servers_owner_id"), "tool_servers", ["owner_id"], unique=False)
    op.create_table(
        "tools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("side_effect", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["tool_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_tool_server_name"),
    )
    op.create_index(op.f("ix_tools_server_id"), "tools", ["server_id"], unique=False)
    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("tool_ref", sa.String(length=160), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tool_call_logs_user_id"), "tool_call_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_tool_call_logs_run_id"), "tool_call_logs", ["run_id"], unique=False)
    op.add_column(
        "conversations",
        sa.Column("disabled_tool_refs", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("conversations", "disabled_tool_refs")
    op.drop_table("tool_call_logs")
    op.drop_table("tools")
    op.drop_table("tool_servers")
