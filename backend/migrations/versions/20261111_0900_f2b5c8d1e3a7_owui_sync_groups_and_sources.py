"""groups, their members and the origin of the collections and documents copied from Open WebUI (#453)

Revision ID: f2b5c8d1e3a7
Revises: e1a4b7c0d2f6
Create Date: 2026-11-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b5c8d1e3a7"
down_revision: str | Sequence[str] | None = "e1a4b7c0d2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="muffin", nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_groups_source_external_id",
        "groups",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    for table in ("collections", "documents"):
        op.add_column(table, sa.Column("source", sa.String(length=16), server_default="muffin", nullable=False))
        op.add_column(table, sa.Column("external_id", sa.String(), nullable=True))
        op.create_index(
            f"uq_{table}_source_external_id",
            table,
            ["source", "external_id"],
            unique=True,
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("documents", "collections"):
        op.drop_index(
            f"uq_{table}_source_external_id", table_name=table, postgresql_where=sa.text("external_id IS NOT NULL")
        )
        op.drop_column(table, "external_id")
        op.drop_column(table, "source")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index(
        "uq_groups_source_external_id", table_name="groups", postgresql_where=sa.text("external_id IS NOT NULL")
    )
    op.drop_table("groups")
