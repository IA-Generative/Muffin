"""read or write on a collection share (#454)

Revision ID: b4d7e0f3a5c9
Revises: a3c6d9e2f4b8
Create Date: 2026-11-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d7e0f3a5c9"
down_revision: str | Sequence[str] | None = "a3c6d9e2f4b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The shares that exist let their person read: that is what they keep.
    op.add_column(
        "collection_shares", sa.Column("permission", sa.String(length=16), server_default="read", nullable=False)
    )
    op.create_check_constraint(
        "ck_collection_shares_permission", "collection_shares", "permission IN ('read', 'write')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_collection_shares_permission", "collection_shares", type_="check")
    op.drop_column("collection_shares", "permission")
