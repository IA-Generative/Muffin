"""add draft upload origin and base preview

Revision ID: a43c9a9fd2c0
Revises: 7f754413fc28
Create Date: 2026-10-22 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a43c9a9fd2c0"
down_revision: str | Sequence[str] | None = "7f754413fc28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("document_drafts", sa.Column("origin", sa.String(), server_default="chat", nullable=False))
    op.add_column("document_drafts", sa.Column("filename", sa.String(), nullable=True))
    op.add_column("document_drafts", sa.Column("base_preview_pdf_key", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("document_drafts", "base_preview_pdf_key")
    op.drop_column("document_drafts", "filename")
    op.drop_column("document_drafts", "origin")
