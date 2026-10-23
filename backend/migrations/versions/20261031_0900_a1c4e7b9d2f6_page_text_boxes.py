"""keep the positioned text of each page: its lines and words, with their boxes (#350)

Revision ID: a1c4e7b9d2f6
Revises: f9b3d7c1e5a8
Create Date: 2026-10-31 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1c4e7b9d2f6"
down_revision: str | Sequence[str] | None = "f9b3d7c1e5a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "page_text_boxes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_page_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column(
            "words", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_page_id"], ["document_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_page_text_boxes_document_page_id"), "page_text_boxes", ["document_page_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_page_text_boxes_document_page_id"), table_name="page_text_boxes")
    op.drop_table("page_text_boxes")
