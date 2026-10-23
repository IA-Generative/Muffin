"""the pages a document's summary was made from, when it read only a part of it (#372)

Revision ID: e5a8c1d4f6b0
Revises: d4f7b0c3e5a9
Create Date: 2026-11-04 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5a8c1d4f6b0"
down_revision: str | Sequence[str] | None = "d4f7b0c3e5a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("summary_pages", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documents", "summary_pages")
