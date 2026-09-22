"""add cgu versioning and acceptance tracking

Revision ID: 142eabf70756
Revises: 0e2dfb8a4e41
Create Date: 2026-09-22 07:49:40.051873

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "142eabf70756"
down_revision: str | Sequence[str] | None = "0e2dfb8a4e41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed content (§127) - a genuinely usable default rather than a placeholder, so acceptance is
# actually enforceable from the first deployment onward, not left blank until an admin gets
# around to writing real CGU. Deliberately flags this as a test/beta deployment and warns against
# uploading sensitive data, since that's the actual state of things today - an admin publishing a
# new version (create + activate, same pattern as prompt versioning, §96) supersedes this exactly
# the way any other content here would.
_CGU_V1 = """\
# Conditions générales d'utilisation

## Article 1 - Objet

Les présentes conditions générales d'utilisation (CGU) régissent l'accès et l'utilisation de \
Muffin (« le Service »), un outil de recherche documentaire et de question-réponse assisté par \
intelligence artificielle. Toute utilisation du Service implique l'acceptation pleine et \
entière des présentes CGU.

## Article 2 - Avertissement : version de test

**Le Service est actuellement mis à disposition dans le cadre d'une phase de test.** À ce \
titre :

- Les fonctionnalités, leur comportement et les présentes CGU sont susceptibles d'évoluer \
fréquemment et sans préavis long.
- La disponibilité, la performance et la conservation des données ne sont pas garanties. Une \
interruption de service, une perte de données ou une réinitialisation de l'environnement \
peuvent survenir à tout moment durant cette phase.
- **Il est demandé de ne déposer aucune donnée sensible, confidentielle ou à caractère \
personnel critique** (données de santé, données financières sensibles, secrets professionnels, \
etc.) tant que le Service n'est pas passé en phase de production stabilisée.

## Article 3 - Description du service

Le Service permet à l'utilisateur de constituer des collections de documents, d'y poser des \
questions en langage naturel et d'obtenir des réponses générées par un modèle de langage, \
appuyées sur le contenu de ces documents. Les réponses générées peuvent contenir des erreurs ou \
des approximations : elles doivent être vérifiées avant toute utilisation dans un contexte \
décisionnel.

## Article 4 - Compte utilisateur et responsabilité

L'accès au Service est personnel et authentifié. L'utilisateur est responsable de l'usage qu'il \
fait du Service et des documents qu'il y dépose, notamment du respect des droits de propriété \
intellectuelle et de la réglementation applicable aux données qu'il y verse.

## Article 5 - Évolution des présentes CGU

Les présentes CGU peuvent être mises à jour. En cas de modification, une nouvelle acceptation \
explicite est demandée à l'utilisateur avant de pouvoir continuer à utiliser le Service - la \
version qu'il a acceptée, et la date de cette acceptation, sont conservées à des fins de \
traçabilité.

## Article 6 - Contact

Pour toute question relative aux présentes CGU, contacter l'équipe responsable du Service.
"""


def upgrade() -> None:
    """Upgrade schema."""
    cgu_versions = op.create_table(
        "cgu_versions",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_cgu_versions_version"),
    )
    op.create_table(
        "cgu_acceptances",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("cgu_version_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["cgu_version_id"], ["cgu_versions.id"], ondelete="CASCADE", name="fk_cgu_acceptances_cgu_version_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "cgu_version_id", name="uq_cgu_acceptances_user_version"),
    )
    op.create_index(op.f("ix_cgu_acceptances_cgu_version_id"), "cgu_acceptances", ["cgu_version_id"], unique=False)
    op.create_index(op.f("ix_cgu_acceptances_user_id"), "cgu_acceptances", ["user_id"], unique=False)

    op.bulk_insert(
        cgu_versions,
        [{"id": uuid.uuid4(), "version": 1, "content": _CGU_V1, "is_active": True}],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_cgu_acceptances_user_id"), table_name="cgu_acceptances")
    op.drop_index(op.f("ix_cgu_acceptances_cgu_version_id"), table_name="cgu_acceptances")
    op.drop_table("cgu_acceptances")
    op.drop_table("cgu_versions")
