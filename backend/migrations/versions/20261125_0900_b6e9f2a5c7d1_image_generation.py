"""image generation in the chat: its settings, the images, and what they cost (#518)

Revision ID: b6e9f2a5c7d1
Revises: a5d8e1f4b6c0
Create Date: 2026-11-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6e9f2a5c7d1"
down_revision: str | Sequence[str] | None = "a5d8e1f4b6c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "image_generation_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("edit_model", sa.String(length=200), nullable=True),
        sa.Column("size", sa.String(length=20), server_default="1024x1024", nullable=False),
        sa.Column("quality", sa.String(length=20), nullable=True),
        sa.Column("daily_limit", sa.Integer(), server_default="20", nullable=False),
        sa.Column("max_image_bytes", sa.Integer(), server_default="8388608", nullable=False),
        sa.Column("allowed_groups", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "message_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("s3_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_message_images_origin"), "message_images", ["origin"], unique=False)
    op.create_index(op.f("ix_message_images_conversation_id"), "message_images", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_message_images_message_id"), "message_images", ["message_id"], unique=False)
    op.create_index(op.f("ix_message_images_run_id"), "message_images", ["run_id"], unique=False)
    op.create_index(op.f("ix_message_images_user_id"), "message_images", ["user_id"], unique=False)
    # A new value of an enum cannot be used in the transaction that adds it. The labels are the names of the members.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE token_usage_kind ADD VALUE IF NOT EXISTS 'IMAGE'")
    op.add_column("token_usages", sa.Column("images", sa.Integer(), server_default="0", nullable=False))
    op.add_column("token_usages", sa.Column("pixels", sa.BigInteger(), server_default="0", nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("token_usages", "pixels")
    op.drop_column("token_usages", "images")
    op.drop_index(op.f("ix_message_images_user_id"), table_name="message_images")
    op.drop_index(op.f("ix_message_images_run_id"), table_name="message_images")
    op.drop_index(op.f("ix_message_images_message_id"), table_name="message_images")
    op.drop_index(op.f("ix_message_images_conversation_id"), table_name="message_images")
    op.drop_index(op.f("ix_message_images_origin"), table_name="message_images")
    op.drop_table("message_images")
    op.drop_table("image_generation_settings")
