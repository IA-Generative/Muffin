"""the accounts of the synchronisations with Open WebUI, and when each copy was last synchronised (#466)

Revision ID: d6f9a2b5c7e1
Revises: c5e8f1a4b6d0
Create Date: 2026-11-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d6f9a2b5c7e1"
down_revision: str | Sequence[str] | None = "c5e8f1a4b6d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "owui_sync_runs",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.add_column("collections", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("collections", sa.Column("sync_problems", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("collections", "sync_problems")
    op.drop_column("collections", "synced_at")
    op.drop_table("owui_sync_runs")
