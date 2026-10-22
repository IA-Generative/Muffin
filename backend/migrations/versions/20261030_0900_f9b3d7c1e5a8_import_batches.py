"""track the batches of files a big ZIP import is read in (#334)

Revision ID: f9b3d7c1e5a8
Revises: e8a2c6b0d4f7
Create Date: 2026-10-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f9b3d7c1e5a8"
down_revision: str | Sequence[str] | None = "e8a2c6b0d4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    for column, default in (("batches_expected", "[]"), ("batches_done", "[]"), ("batch_results", "{}")):
        op.add_column(
            "collection_imports",
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text(f"'{default}'::jsonb"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in ("batch_results", "batches_done", "batches_expected"):
        op.drop_column("collection_imports", column)
