"""the time, CPU and memory of the worker tasks and the agent's steps (execution_metrics)

Revision ID: f6b9d2e5a7c1
Revises: e5a8c1d4f6b0
Create Date: 2026-11-05 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6b9d2e5a7c1"
down_revision: str | Sequence[str] | None = "e5a8c1d4f6b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "execution_metrics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("cpu_seconds", sa.Float(), nullable=False),
        sa.Column("peak_rss_bytes", sa.BigInteger(), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_execution_metrics_user_id"), "execution_metrics", ["user_id"])
    op.create_index(op.f("ix_execution_metrics_created_at"), "execution_metrics", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_execution_metrics_created_at"), table_name="execution_metrics")
    op.drop_index(op.f("ix_execution_metrics_user_id"), table_name="execution_metrics")
    op.drop_table("execution_metrics")
