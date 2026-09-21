"""add temporary collection fields

Revision ID: 3e2a4a8c7bec
Revises: d3ef9214b942
Create Date: 2026-09-21 19:18:59.287606

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e2a4a8c7bec"
down_revision: str | Sequence[str] | None = "d3ef9214b942"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("collections", sa.Column("is_temporary", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("collections", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.create_unique_constraint("uq_collections_conversation_id", "collections", ["conversation_id"])
    op.create_foreign_key(
        "fk_collections_conversation_id_conversations",
        "collections",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_collections_conversation_id_conversations", "collections", type_="foreignkey")
    op.drop_constraint("uq_collections_conversation_id", "collections", type_="unique")
    op.drop_column("collections", "conversation_id")
    op.drop_column("collections", "is_temporary")
