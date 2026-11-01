"""assistants: named settings for the chat, shared like collections (#514)

Revision ID: d2f5a8b1c3e7
Revises: c1e4f7a0b2d6
Create Date: 2026-11-21 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d2f5a8b1c3e7"
down_revision: str | Sequence[str] | None = "c1e4f7a0b2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Existing types, made for the collections.
visibility = postgresql.ENUM("PRIVATE", "PUBLIC", name="collection_visibility", create_type=False)
subject_type = postgresql.ENUM("USER", "GROUP", name="share_subject_type", create_type=False)
share_status = postgresql.ENUM("PENDING", "ACTIVE", name="share_status", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "assistants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("icon", sa.String(length=16), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("hide_instructions", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("collection_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("include_descendants", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("web_search_allowed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disabled_tools", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("visibility", visibility, server_default="PRIVATE", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_assistants_owner_id"), "assistants", ["owner_id"], unique=False)
    op.create_table(
        "assistant_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=False),
        sa.Column("subject_type", subject_type, nullable=False),
        sa.Column("status", share_status, nullable=False),
        sa.Column("permission", sa.String(length=16), server_default="read", nullable=False),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("invited_identifier_hash", sa.String(), nullable=True),
        sa.Column("display_hint", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], ["assistants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_id", "subject_type", "invited_identifier_hash", name="uq_assistant_share_pending_identifier"
        ),
        sa.UniqueConstraint("assistant_id", "subject_type", "subject_id", name="uq_assistant_share_active_subject"),
    )
    op.create_index(op.f("ix_assistant_shares_assistant_id"), "assistant_shares", ["assistant_id"], unique=False)
    op.create_index(op.f("ix_assistant_shares_status"), "assistant_shares", ["status"], unique=False)
    op.create_index(
        op.f("ix_assistant_shares_invited_identifier_hash"), "assistant_shares", ["invited_identifier_hash"]
    )

    op.add_column("runs", sa.Column("assistant_id", sa.UUID(), nullable=True))
    op.add_column("runs", sa.Column("assistant_name", sa.String(length=100), nullable=True))
    op.add_column("runs", sa.Column("assistant_version", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("assistant_instructions", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("assistant_disabled_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("runs", sa.Column("scope_locked", sa.Boolean(), server_default="false", nullable=False))
    op.create_index(op.f("ix_runs_assistant_id"), "runs", ["assistant_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_runs_assistant_id"), table_name="runs")
    op.drop_column("runs", "scope_locked")
    op.drop_column("runs", "assistant_disabled_tools")
    op.drop_column("runs", "assistant_instructions")
    op.drop_column("runs", "assistant_version")
    op.drop_column("runs", "assistant_name")
    op.drop_column("runs", "assistant_id")
    op.drop_table("assistant_shares")
    op.drop_table("assistants")
