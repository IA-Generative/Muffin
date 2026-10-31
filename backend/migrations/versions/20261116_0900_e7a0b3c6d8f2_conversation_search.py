"""full-text search of the conversations: a French configuration blind to accents, the words of each message (#509)

Revision ID: e7a0b3c6d8f2
Revises: d6f9a2b5c7e1
Create Date: 2026-11-16 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a0b3c6d8f2"
down_revision: str | Sequence[str] | None = "d6f9a2b5c7e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # `unaccent` is a trusted extension (PostgreSQL 13+): the owner of the database may create it. The configuration
    # is a copy of `french` whose words go through `unaccent` first, so that "conges" finds "congés"; being a text
    # search configuration, `to_tsvector` with it is immutable, which a generated column needs (`unaccent()` is not).
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE TEXT SEARCH CONFIGURATION muffin_french (COPY = french)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION muffin_french "
        "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem"
    )
    # The words of a message, kept with it: a search then reads them instead of parsing the text of every message of the
    # user again (measured: 216 ms against a few ms for the 10 000 messages of one user).
    op.execute(
        "ALTER TABLE messages ADD COLUMN content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('muffin_french'::regconfig, content)) STORED"
    )
    op.execute("CREATE INDEX ix_messages_content_tsv ON messages USING gin (content_tsv)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_messages_content_tsv")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS content_tsv")
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS muffin_french")
    # The extension stays: something else may use it.
