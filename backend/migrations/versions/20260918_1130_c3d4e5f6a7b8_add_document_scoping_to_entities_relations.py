"""add document scoping to entities and relations

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-18 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "entity_documents",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("mentions", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id", "document_id"),
    )

    op.add_column("relations", sa.Column("document_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_relations_document_id"), "relations", ["document_id"], unique=False)
    op.create_foreign_key(
        "relations_document_id_fkey", "relations", "documents", ["document_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("relations_document_id_fkey", "relations", type_="foreignkey")
    op.drop_index(op.f("ix_relations_document_id"), table_name="relations")
    op.drop_column("relations", "document_id")

    op.drop_table("entity_documents")
