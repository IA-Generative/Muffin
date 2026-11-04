"""model auto routing

Revision ID: c4f9b2d6e758
Revises: b3e8a1c5d647
Create Date: 2026-11-04 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f9b2d6e758"
down_revision: str | Sequence[str] | None = "b3e8a1c5d647"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "model_profiles",
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("score", sa.Integer(), server_default="50", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("auto_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )
    op.add_column("app_settings", sa.Column("classifier_model", sa.String(length=200), nullable=True))
    op.add_column("runs", sa.Column("requested_model", sa.String(length=200), nullable=True))
    op.add_column("runs", sa.Column("routing", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "routing")
    op.drop_column("runs", "requested_model")
    op.drop_column("app_settings", "classifier_model")
    op.drop_table("model_profiles")
