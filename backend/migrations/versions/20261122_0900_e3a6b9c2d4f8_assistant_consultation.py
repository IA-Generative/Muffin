"""assistants that may consult other assistants (#531)

Revision ID: e3a6b9c2d4f8
Revises: d2f5a8b1c3e7
Create Date: 2026-11-22 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3a6b9c2d4f8"
down_revision: str | Sequence[str] | None = "d2f5a8b1c3e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("assistants", sa.Column("consult_mode", sa.String(length=8), server_default="none", nullable=False))
    op.add_column(
        "assistants",
        sa.Column(
            "consult_assistant_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column("runs", sa.Column("consultable_assistants", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "consultable_assistants")
    op.drop_column("assistants", "consult_assistant_ids")
    op.drop_column("assistants", "consult_mode")
