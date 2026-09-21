"""add filing suggestion fields to documents

Revision ID: de60b21ac164
Revises: 88c0e06ef234
Create Date: 2026-09-21 23:29:57.934711

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "de60b21ac164"
down_revision: str | Sequence[str] | None = "88c0e06ef234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("added_by_user_id", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("added_by_display", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("suggested_collection_id", sa.UUID(), nullable=True))
    op.add_column("documents", sa.Column("suggested_collection_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("filing_dismissed", sa.Boolean(), server_default="false", nullable=False))
    op.create_foreign_key(
        "fk_documents_suggested_collection_id_collections",
        "documents",
        "collections",
        ["suggested_collection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_documents_suggested_collection_id_collections", "documents", type_="foreignkey")
    op.drop_column("documents", "filing_dismissed")
    op.drop_column("documents", "suggested_collection_score")
    op.drop_column("documents", "suggested_collection_id")
    op.drop_column("documents", "added_by_display")
    op.drop_column("documents", "added_by_user_id")
