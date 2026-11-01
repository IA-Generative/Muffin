"""routines and notifications (#524)

Revision ID: c7f3a9b1d2e4
Revises: b6e9f2a5c7d1
Create Date: 2026-11-01 21:03:53.755552

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7f3a9b1d2e4"
down_revision: str | Sequence[str] | None = "b6e9f2a5c7d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("channel", sa.String(length=16), server_default="app", nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "type", "channel"),
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), server_default="", nullable=False),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "read_at"], unique=False)
    op.create_table(
        "routine_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("max_active_per_user", sa.Integer(), server_default="5", nullable=False),
        sa.Column("min_interval_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_runs_per_user_per_day", sa.Integer(), server_default="10", nullable=False),
        sa.Column("max_concurrent", sa.Integer(), server_default="3", nullable=False),
        sa.Column("max_consecutive_failures", sa.Integer(), server_default="3", nullable=False),
        sa.Column("inactive_days", sa.Integer(), server_default="60", nullable=False),
        sa.Column("run_timeout_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "routines",
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("owner_display", sa.String(), server_default="", nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("collection_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("include_descendants", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("assistant_id", sa.UUID(), nullable=True),
        sa.Column("web_search", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("kind", sa.Enum("INTERVAL", "DAILY", "WEEKLY", "MONTHLY", name="routine_kind"), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("time_of_day", sa.Time(), nullable=True),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("day_of_month", sa.SmallInteger(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("condition", sa.Enum("ALWAYS", "ONLY_IF_NEW", name="routine_condition"), nullable=False),
        sa.Column(
            "result_mode",
            sa.Enum("NEW_CONVERSATION", "SINGLE_CONVERSATION", name="routine_result_mode"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("notify", sa.Enum("ALWAYS", "FAILURE", "NEVER", name="routine_notify"), nullable=False),
        sa.Column("state", sa.Enum("ACTIVE", "PAUSED", "SUSPENDED", name="routine_state"), nullable=False),
        sa.Column("suspended_reason", sa.String(length=32), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], ["assistants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_routines_next_run_at"), "routines", ["next_run_at"], unique=False)
    op.create_index(op.f("ix_routines_owner_id"), "routines", ["owner_id"], unique=False)
    op.create_index(op.f("ix_routines_state"), "routines", ["state"], unique=False)
    op.create_table(
        "routine_runs",
        sa.Column("routine_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column(
            "status", sa.Enum("RUNNING", "SUCCEEDED", "FAILED", "SKIPPED", name="routine_run_status"), nullable=False
        ),
        sa.Column("skip_reason", sa.String(length=32), nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["routine_id"], ["routines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_routine_runs_routine_id"), "routine_runs", ["routine_id"], unique=False)
    op.create_index(op.f("ix_routine_runs_run_id"), "routine_runs", ["run_id"], unique=False)
    op.create_index(op.f("ix_routine_runs_started_at"), "routine_runs", ["started_at"], unique=False)
    op.add_column("user_profiles", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_profiles",
        sa.Column("groups", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_profiles", "groups")
    op.drop_column("user_profiles", "last_seen_at")
    op.drop_index(op.f("ix_routine_runs_started_at"), table_name="routine_runs")
    op.drop_index(op.f("ix_routine_runs_run_id"), table_name="routine_runs")
    op.drop_index(op.f("ix_routine_runs_routine_id"), table_name="routine_runs")
    op.drop_table("routine_runs")
    op.drop_index(op.f("ix_routines_state"), table_name="routines")
    op.drop_index(op.f("ix_routines_owner_id"), table_name="routines")
    op.drop_index(op.f("ix_routines_next_run_at"), table_name="routines")
    op.drop_table("routines")
    op.drop_table("routine_settings")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("notification_preferences")
    for name in (
        "routine_run_status",
        "routine_notify",
        "routine_result_mode",
        "routine_condition",
        "routine_state",
        "routine_kind",
    ):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
