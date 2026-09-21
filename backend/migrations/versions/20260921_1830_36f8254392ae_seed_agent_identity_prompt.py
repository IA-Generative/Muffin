"""seed agent_identity prompt and bump analyze_query to v2

Revision ID: 36f8254392ae
Revises: 4a5f9d2f6c06
Create Date: 2026-09-21 18:30:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "36f8254392ae"
down_revision: str | Sequence[str] | None = "4a5f9d2f6c06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# New prompt (issue #99): worker/agent_execution/app/graph/nodes/answer_identity.py's
# _SYSTEM_PROMPT fallback, copied verbatim as version 1, active.
_AGENT_IDENTITY_V1 = (
    "You are Muffin, an internal assistant that answers questions by searching the user's own knowledge base "
    "collections (and the web, only when the user has explicitly enabled it for this conversation). The user "
    "is asking about you rather than about their documents - introduce yourself briefly by name, then describe "
    "what you can do using only the capabilities listed below. Never invent a capability that isn't listed, "
    "never claim general knowledge beyond what those tools can actually do. Keep the answer short, friendly, "
    "and respond in the same language as the user's query."
)

# Updated worker/agent_execution/app/graph/nodes/analyze_query.py's _SYSTEM_PROMPT fallback,
# adding the "identity" intent (§99) so "qui es-tu ?" routes to answer_identity instead of
# falling through decompose_query/search and coming back empty-handed (§97).
_ANALYZE_QUERY_V2 = (
    "Analyze the user's current question, in light of the conversation so far if any is given. Respond only "
    'with a JSON object with keys: "intent" (one of "lookup", "comparison", "synthesis", "meta", "identity"), '
    '"topics" (array of short strings), "requires_multiple_sources" (bool), "complexity" (one of "simple", '
    '"complex"), "ambiguous" (bool - true only if the question is still unclear once the conversation history '
    'is taken into account), "clarification_question" (string or null, only set if ambiguous is true), '
    '"standalone_query" (string - the current question rewritten to stand on its own, resolving any pronoun '
    'or reference back to something said earlier in the conversation, e.g. "elle"/"it" -> the thing it '
    "refers to; if the question is already self-contained or there is no conversation history, repeat it "
    "unchanged).\n\n"
    'Use "meta" when the query is about the knowledge bases themselves rather than their content - e.g. '
    "how many collections/documents the user has access to, a collection's or document's summary, or the "
    "content/screenshot of one specific page, rather than a document/policy question that content search "
    "should answer.\n\n"
    'Use "identity" when the query is about the agent itself rather than about the user\'s documents - e.g. '
    '"who are you?", "what can you do?", "what is your name?" - never for a question that happens to mention '
    '"you" while still asking about document content.\n\n'
    'IMPORTANT - be very conservative with "ambiguous": only set it to true if the question is truly '
    "unanswerable without more information. The user has already selected one or more collections to query "
    'against, so references like "le fichier", "les données", "the data", "the file" are NOT ambiguous - '
    "they refer to the selected collection(s). Questions about columns, rows, averages, counts, sums, or "
    "any analytical operation on tabular data are NOT ambiguous even if they don't name a specific file. "
    "When in doubt, set ambiguous to false - it is better to attempt an answer than to block the user with "
    "a clarification question."
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
    conn = op.get_bind()

    # New prompt, seeded active - same pattern as the six seeded by the previous migration.
    conn.execute(
        _prompt_versions.insert().values(
            id=uuid.uuid4(), name="agent_identity", version=1, content=_AGENT_IDENTITY_V1, is_active=True
        )
    )

    # Publish analyze_query v2 through the same mechanism the admin UI uses (create + activate,
    # see PromptRepository.create_version/activate) rather than editing the v1 row in place -
    # v1 stays in the history, exactly like a real admin publish would leave it.
    current_version = conn.execute(
        sa.select(sa.func.max(_prompt_versions.c.version)).where(_prompt_versions.c.name == "analyze_query")
    ).scalar_one()
    conn.execute(
        _prompt_versions.update()
        .where(_prompt_versions.c.name == "analyze_query", _prompt_versions.c.is_active.is_(True))
        .values(is_active=False)
    )
    conn.execute(
        _prompt_versions.insert().values(
            id=uuid.uuid4(),
            name="analyze_query",
            version=current_version + 1,
            content=_ANALYZE_QUERY_V2,
            is_active=True,
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    conn.execute(_prompt_versions.delete().where(_prompt_versions.c.name == "agent_identity"))

    max_version = conn.execute(
        sa.select(sa.func.max(_prompt_versions.c.version)).where(_prompt_versions.c.name == "analyze_query")
    ).scalar_one()
    conn.execute(
        _prompt_versions.delete().where(
            _prompt_versions.c.name == "analyze_query", _prompt_versions.c.version == max_version
        )
    )
    conn.execute(
        _prompt_versions.update()
        .where(_prompt_versions.c.name == "analyze_query", _prompt_versions.c.version == max_version - 1)
        .values(is_active=True)
    )
