"""add URL refresh schedules and the content hash of a fetched page

Revision ID: d1e5a7c3f9b2
Revises: c8d2f4a6b1e9
Create Date: 2026-10-23 15:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d1e5a7c3f9b2"
down_revision: str | Sequence[str] | None = "c8d2f4a6b1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The help guide (app_help, #251) said a URL page is read once and never refreshed: no longer true.
# The new paragraph replaces the old one in whatever version is active, so an admin's other edits of
# the guide survive; nothing is published if they already reworded it.
_GUIDE_OLD = (
    "- Dans l'onglet « Documents » : glisser-déposer des fichiers ou « cliquer pour parcourir » ; "
    "saisir une URL dans « Ajouter une URL à indexer… » (la page est lue une fois, elle n'est pas "
    "rafraîchie automatiquement) ; ajouter un document vivant (bouton « Document vivant », fichiers "
    ".odt ou .md) ou en écrire un nouveau en Markdown (« Nouveau document Markdown »)."
)
_GUIDE_NEW = (
    "- Dans l'onglet « Documents » : glisser-déposer des fichiers ou « cliquer pour parcourir » ; "
    "saisir une URL dans « Ajouter une URL à indexer… » ; ajouter un document vivant (« Ajouter un "
    "document vivant », fichiers .odt ou .md) ou en écrire un nouveau en Markdown (« Créer un "
    "document Markdown »).\n"
    "- Une page ajoutée par URL peut être relue automatiquement : sur la fiche du document, « Mise à "
    "jour automatique » propose une fréquence, de « Toutes les 30 minutes » à « Toutes les semaines "
    "» (« Jamais » par défaut). Si le contenu de la page a changé, le document est entièrement "
    "réindexé (résumé, questions-réponses, entités, tags) ; sinon rien ne change. Seul le "
    "propriétaire de la collection règle la fréquence."
)

_prompt_versions = sa.table(
    "prompt_versions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("name", sa.String),
    sa.column("version", sa.Integer),
    sa.column("content", sa.Text),
    sa.column("is_active", sa.Boolean),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "document_refresh_schedules",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_refresh_schedules_document_id"), "document_refresh_schedules", ["document_id"], unique=True
    )
    op.create_index(
        op.f("ix_document_refresh_schedules_next_run_at"), "document_refresh_schedules", ["next_run_at"], unique=False
    )
    _publish_guide(_GUIDE_OLD, _GUIDE_NEW)


def downgrade() -> None:
    """Downgrade schema."""
    _unpublish_guide()
    op.drop_index(op.f("ix_document_refresh_schedules_next_run_at"), table_name="document_refresh_schedules")
    op.drop_index(op.f("ix_document_refresh_schedules_document_id"), table_name="document_refresh_schedules")
    op.drop_table("document_refresh_schedules")
    op.drop_column("documents", "last_fetched_at")
    op.drop_column("documents", "content_hash")


def _publish_guide(old: str, new: str) -> None:
    conn = op.get_bind()
    active = conn.execute(
        sa.select(_prompt_versions.c.content).where(
            _prompt_versions.c.name == "app_help", _prompt_versions.c.is_active.is_(True)
        )
    ).scalar_one_or_none()
    if active is None or old not in active:
        return
    latest = conn.execute(
        sa.select(sa.func.max(_prompt_versions.c.version)).where(_prompt_versions.c.name == "app_help")
    ).scalar_one()
    conn.execute(
        _prompt_versions.update()
        .where(_prompt_versions.c.name == "app_help", _prompt_versions.c.is_active.is_(True))
        .values(is_active=False)
    )
    conn.execute(
        _prompt_versions.insert().values(
            id=uuid.uuid4(), name="app_help", version=latest + 1, content=active.replace(old, new), is_active=True
        )
    )


def _unpublish_guide() -> None:
    """Only the version this migration published goes: a later one is the admin's."""
    conn = op.get_bind()
    latest = conn.execute(
        sa.select(_prompt_versions.c.version, _prompt_versions.c.content)
        .where(_prompt_versions.c.name == "app_help")
        .order_by(_prompt_versions.c.version.desc())
        .limit(1)
    ).first()
    if latest is None or _GUIDE_NEW not in latest.content or latest.version == 1:
        return
    conn.execute(
        _prompt_versions.delete().where(
            _prompt_versions.c.name == "app_help", _prompt_versions.c.version == latest.version
        )
    )
    conn.execute(
        _prompt_versions.update()
        .where(_prompt_versions.c.name == "app_help", _prompt_versions.c.version == latest.version - 1)
        .values(is_active=True)
    )
