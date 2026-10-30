"""the owner of a group, and members invited by email who have not signed in yet (#455)

Revision ID: a3c6d9e2f4b8
Revises: f2b5c8d1e3a7
Create Date: 2026-11-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c6d9e2f4b8"
down_revision: str | Sequence[str] | None = "f2b5c8d1e3a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("groups", sa.Column("owner_id", sa.String(), nullable=True))
    op.create_index("ix_groups_owner_id", "groups", ["owner_id"])

    # (group, user) was the key; an invited member has no user yet, so a row of its own gets an id.
    op.add_column("group_members", sa.Column("id", sa.UUID(), nullable=True))
    op.execute("UPDATE group_members SET id = gen_random_uuid()")
    op.drop_constraint("group_members_pkey", "group_members", type_="primary")
    op.alter_column("group_members", "id", nullable=False)
    op.create_primary_key("group_members_pkey", "group_members", ["id"])
    op.alter_column("group_members", "user_id", nullable=True)
    op.add_column("group_members", sa.Column("status", sa.String(length=16), server_default="active", nullable=False))
    op.add_column("group_members", sa.Column("invited_identifier_hash", sa.String(), nullable=True))
    op.add_column("group_members", sa.Column("display_hint", sa.String(), nullable=True))
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_status", "group_members", ["status"])
    op.create_index("ix_group_members_invited_identifier_hash", "group_members", ["invited_identifier_hash"])
    op.create_unique_constraint("uq_group_members_group_user", "group_members", ["group_id", "user_id"])
    op.create_unique_constraint(
        "uq_group_members_pending_identifier", "group_members", ["group_id", "invited_identifier_hash"]
    )
    op.create_check_constraint(
        "ck_group_members_status_fields",
        "group_members",
        "(status = 'active' AND user_id IS NOT NULL) OR (status = 'pending' AND invited_identifier_hash IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM group_members WHERE status = 'pending'")
    op.drop_constraint("ck_group_members_status_fields", "group_members", type_="check")
    op.drop_constraint("uq_group_members_pending_identifier", "group_members", type_="unique")
    op.drop_constraint("uq_group_members_group_user", "group_members", type_="unique")
    op.drop_index("ix_group_members_invited_identifier_hash", table_name="group_members")
    op.drop_index("ix_group_members_status", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_column("group_members", "display_hint")
    op.drop_column("group_members", "invited_identifier_hash")
    op.drop_column("group_members", "status")
    op.alter_column("group_members", "user_id", nullable=False)
    op.drop_constraint("group_members_pkey", "group_members", type_="primary")
    op.drop_column("group_members", "id")
    op.create_primary_key("group_members_pkey", "group_members", ["group_id", "user_id"])

    op.drop_index("ix_groups_owner_id", table_name="groups")
    op.drop_column("groups", "owner_id")
