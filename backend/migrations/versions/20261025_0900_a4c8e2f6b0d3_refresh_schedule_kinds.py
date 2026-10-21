"""URL refresh schedules: once, every day, some days of the week or every N minutes

Revision ID: a4c8e2f6b0d3
Revises: f3a7c9e1b5d2
Create Date: 2026-10-25 09:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a4c8e2f6b0d3"
down_revision: str | Sequence[str] | None = "f3a7c9e1b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_refresh_kind = postgresql.ENUM("ONCE", "DAILY", "WEEKLY", "INTERVAL", name="refresh_kind", create_type=False)

# The help guide (app_help) described a frequency picked on the document's page only. Same approach
# as d1e5a7c3f9b2: the paragraph is replaced in the active version, nothing published if an admin
# already reworded it.
_GUIDE_OLD = (
    "- Une page ajoutée par URL peut être relue automatiquement : sur la fiche du document, « Mise à "
    "jour automatique » propose une fréquence, de « Toutes les 30 minutes » à « Toutes les semaines "
    "» (« Jamais » par défaut). Si le contenu de la page a changé, le document est entièrement "
    "réindexé (résumé, questions-réponses, entités, tags) ; sinon rien ne change. Seul le "
    "propriétaire de la collection règle la fréquence."
)
_GUIDE_NEW = (
    "- Une URL peut pointer vers une page web ou vers un fichier (PDF, Word, tableur, image…) : un "
    "fichier est téléchargé et traité comme un fichier déposé.\n"
    "- Une URL peut être relue automatiquement. À l'ajout, une fenêtre propose « Mise à jour "
    "automatique » (facultatif), modifiable ensuite sur la fiche du document : « Une fois » à une "
    "date et une heure, « Tous les jours » ou « Certains jours de la semaine » à une heure, ou « À "
    "intervalle régulier » (de 30 minutes à une semaine). Les heures se choisissent à l'heure pile "
    "ou à la demie. Si le contenu a changé, le document est entièrement réindexé (résumé, "
    "questions-réponses, entités, tags) ; sinon rien ne change. Seul le propriétaire de la "
    "collection règle la mise à jour."
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
    _refresh_kind.create(op.get_bind(), checkfirst=True)
    # Every schedule so far was an interval.
    op.add_column(
        "document_refresh_schedules",
        sa.Column("kind", _refresh_kind, nullable=False, server_default="INTERVAL"),
    )
    op.alter_column("document_refresh_schedules", "kind", server_default=None)
    op.alter_column("document_refresh_schedules", "interval_minutes", nullable=True)
    op.add_column("document_refresh_schedules", sa.Column("time_of_day", sa.Time(), nullable=True))
    op.add_column(
        "document_refresh_schedules", sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True)
    )
    op.add_column(
        "document_refresh_schedules",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Paris"),
    )
    op.alter_column("document_refresh_schedules", "timezone", server_default=None)
    _publish_guide(_GUIDE_OLD, _GUIDE_NEW)


def downgrade() -> None:
    """Downgrade schema."""
    _unpublish_guide()
    # Only intervals existed before: the other schedules have no equivalent.
    op.execute("DELETE FROM document_refresh_schedules WHERE kind <> 'INTERVAL'")
    op.drop_column("document_refresh_schedules", "timezone")
    op.drop_column("document_refresh_schedules", "weekdays")
    op.drop_column("document_refresh_schedules", "time_of_day")
    op.alter_column("document_refresh_schedules", "interval_minutes", nullable=False)
    op.drop_column("document_refresh_schedules", "kind")
    _refresh_kind.drop(op.get_bind(), checkfirst=True)


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
