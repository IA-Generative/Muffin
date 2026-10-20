"""add collection parent_id (sub-collections)

Revision ID: a44d4216a608
Revises: 4cdf987deaf9
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a44d4216a608"
down_revision: str | Sequence[str] | None = "4cdf987deaf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("collections", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "collections_parent_id_fkey", "collections", "collections", ["parent_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_collections_parent_id"), "collections", ["parent_id"], unique=False)
    op.create_check_constraint("ck_collections_not_own_parent", "collections", "parent_id IS NULL OR parent_id <> id")
    op.create_check_constraint(
        "ck_collections_temporary_has_no_parent", "collections", "NOT (is_temporary AND parent_id IS NOT NULL)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_collections_temporary_has_no_parent", "collections", type_="check")
    op.drop_constraint("ck_collections_not_own_parent", "collections", type_="check")
    op.drop_index(op.f("ix_collections_parent_id"), table_name="collections")
    op.drop_constraint("collections_parent_id_fkey", "collections", type_="foreignkey")
    op.drop_column("collections", "parent_id")
