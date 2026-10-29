"""tasks: persist their status, start and end

The status used to be read live from Celery's result backend, which cannot tell an id it no
longer knows from one still waiting in the queue. The workers now report it as they run the task,
so it is stored here - with when it started, when it ended, and the error it failed on.

Revision ID: b9c3d5e7f1a2
Revises: d0f3a6b9c1e5
Create Date: 2026-11-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b9c3d5e7f1a2"
down_revision: str | Sequence[str] | None = "d0f3a6b9c1e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_STATUS_VALUES = ("PENDING", "STARTED", "SUCCESS", "FAILURE", "REVOKED", "UNKNOWN")


def upgrade() -> None:
    """Upgrade schema."""
    task_status = postgresql.ENUM(*_TASK_STATUS_VALUES, name="task_status", create_type=False)
    task_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "tasks",
        sa.Column("status", task_status, nullable=False, server_default="PENDING"),
    )
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("error", sa.Text(), nullable=True))
    # The rows recorded before this column have no status to recover: UNKNOWN, not PENDING, so
    # that an old task never reads as still queued or running.
    op.execute("UPDATE tasks SET status = 'UNKNOWN'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "error")
    op.drop_column("tasks", "finished_at")
    op.drop_column("tasks", "started_at")
    op.drop_column("tasks", "status")
    postgresql.ENUM(*_TASK_STATUS_VALUES, name="task_status").drop(op.get_bind(), checkfirst=True)
