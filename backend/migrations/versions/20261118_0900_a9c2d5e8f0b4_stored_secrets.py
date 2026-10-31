"""the secrets Muffin must read back, kept encrypted (#521)

Revision ID: a9c2d5e8f0b4
Revises: f8b1c4d7e9a3
Create Date: 2026-11-18 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c2d5e8f0b4"
down_revision: str | Sequence[str] | None = "f8b1c4d7e9a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "stored_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("hint", sa.String(length=8), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stored_secrets_owner_id"), "stored_secrets", ["owner_id"], unique=False)
    op.create_index(op.f("ix_stored_secrets_purpose"), "stored_secrets", ["purpose"], unique=False)
    op.create_index(op.f("ix_stored_secrets_key_version"), "stored_secrets", ["key_version"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_stored_secrets_key_version"), table_name="stored_secrets")
    op.drop_index(op.f("ix_stored_secrets_purpose"), table_name="stored_secrets")
    op.drop_index(op.f("ix_stored_secrets_owner_id"), table_name="stored_secrets")
    op.drop_table("stored_secrets")
