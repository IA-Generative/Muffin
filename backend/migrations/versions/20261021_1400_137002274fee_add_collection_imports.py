"""add collection imports (ZIP import)

Revision ID: 137002274fee
Revises: 7cc7069610f1
Create Date: 2026-10-21 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "137002274fee"
down_revision: str | Sequence[str] | None = "7cc7069610f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


collection_import_status_enum = sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="collection_import_status")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "collection_imports",
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("owner_display", sa.String(), nullable=False),
        sa.Column("archive_name", sa.String(), nullable=False),
        sa.Column("archive_key", sa.String(), nullable=True),
        sa.Column("status", collection_import_status_enum, nullable=False),
        sa.Column("root_collection_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["root_collection_id"], ["collections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_collection_imports_owner_id"), "collection_imports", ["owner_id"], unique=False)
    op.create_index(
        op.f("ix_collection_imports_root_collection_id"), "collection_imports", ["root_collection_id"], unique=False
    )
    op.create_index(
        op.f("ix_collection_imports_conversation_id"), "collection_imports", ["conversation_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_collection_imports_conversation_id"), table_name="collection_imports")
    op.drop_index(op.f("ix_collection_imports_root_collection_id"), table_name="collection_imports")
    op.drop_index(op.f("ix_collection_imports_owner_id"), table_name="collection_imports")
    op.drop_table("collection_imports")
    # drop_table doesn't drop the enum type it used (same pattern as the other enum-backed migrations).
    collection_import_status_enum.drop(op.get_bind(), checkfirst=True)
