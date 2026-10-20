"""add collection import attach suggestion

Revision ID: e59419ac9e72
Revises: 137002274fee
Create Date: 2026-10-21 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e59419ac9e72"
down_revision: str | Sequence[str] | None = "137002274fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "collection_imports", sa.Column("attach_eligible", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("collection_imports", sa.Column("suggested_parent_id", sa.UUID(), nullable=True))
    op.add_column("collection_imports", sa.Column("suggested_parent_score", sa.Float(), nullable=True))
    op.add_column(
        "collection_imports",
        sa.Column("attach_candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "collection_imports", sa.Column("attach_dismissed", sa.Boolean(), server_default="false", nullable=False)
    )
    op.create_foreign_key(
        "collection_imports_suggested_parent_id_fkey",
        "collection_imports",
        "collections",
        ["suggested_parent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("collection_imports_suggested_parent_id_fkey", "collection_imports", type_="foreignkey")
    op.drop_column("collection_imports", "attach_dismissed")
    op.drop_column("collection_imports", "attach_candidates")
    op.drop_column("collection_imports", "suggested_parent_score")
    op.drop_column("collection_imports", "suggested_parent_id")
    op.drop_column("collection_imports", "attach_eligible")
