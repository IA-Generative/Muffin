"""store a task's logs line by line, as they are logged (#305)

Revision ID: d7f1b5a9c3e6
Revises: c6e0a4f8b2d5
Create Date: 2026-10-28 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7f1b5a9c3e6"
down_revision: str | Sequence[str] | None = "c6e0a4f8b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "task_log_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("celery_task_id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("collection_id", sa.UUID(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_log_entries_task", "task_log_entries", ["celery_task_id", "id"])
    op.create_index("ix_task_log_entries_document", "task_log_entries", ["document_id", "id"])
    op.create_index("ix_task_log_entries_ts", "task_log_entries", ["ts"])
    # A task logged before keeps its whole output, as one line. tasks.logs itself stays for a release:
    # a backend not yet upgraded still reads it while this one rolls out.
    op.execute(
        """
        INSERT INTO task_log_entries (celery_task_id, task_name, document_id, collection_id, ts, level, message)
        SELECT celery_task_id, task_name, document_id, collection_id, updated_at, 'INFO', logs
        FROM tasks
        WHERE logs IS NOT NULL AND logs <> ''
        ORDER BY created_at
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_task_log_entries_ts", table_name="task_log_entries")
    op.drop_index("ix_task_log_entries_document", table_name="task_log_entries")
    op.drop_index("ix_task_log_entries_task", table_name="task_log_entries")
    op.drop_table("task_log_entries")
