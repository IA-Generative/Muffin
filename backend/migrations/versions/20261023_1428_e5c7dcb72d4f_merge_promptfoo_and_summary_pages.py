"""merge_promptfoo_and_main

Revision ID: e5c7dcb72d4f
Revises: e485b9098a10, d0f3a6b9c1e5
Create Date: 2026-10-23 14:28:50.756721

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e5c7dcb72d4f"
down_revision: str | Sequence[str] | None = ("e485b9098a10", "d0f3a6b9c1e5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
