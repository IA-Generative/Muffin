"""publish prompt quality improvements (issue #95 + raw-data grounding guidance)

Revision ID: d3ef9214b942
Revises: 36f8254392ae
Create Date: 2026-09-21 19:30:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d3ef9214b942"
down_revision: str | Sequence[str] | None = "36f8254392ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Updated fallbacks from worker/agent_execution/app/graph/nodes/*.py, published the same way an
# admin publish from /admin would (create + activate, previous version kept in history).
_GENERATE_ANSWER_V2 = (
    "Answer the user's query using only the given evidence excerpts. Cite each claim with its excerpt id "
    "in brackets, e.g. [abc123]. Never invent facts not supported by the excerpts. If the evidence notes "
    "some information is missing, say so plainly instead of guessing or narrating your internal process. "
    "If the evidence suggests enabling web search, relay that suggestion in your answer (translated into "
    "the response's language if needed) instead of dropping it. "
    'If the query asks for a count (e.g. "how many collections/documents"), each excerpt below already '
    "represents one distinct item unless it says otherwise - count the excerpts and state that number "
    "directly. Never refuse to count just because no single excerpt states the total as a sentence.\n\n"
    "Formatting:\n"
    "- Use markdown for structure: **bold** for key numbers, `code` for column names.\n"
    "- When the evidence contains tabular results (SQL query results with rows and columns), "
    "format the answer as a markdown table with proper headers and alignment.\n"
    "- When listing multiple items (e.g. top 5, rankings), use a markdown table with a rank column.\n"
    "- For a single value answer (e.g. a count, an average), state it directly and prominently in bold.\n"
    "- For grouped/comparison results, always use a markdown table - never a plain text list.\n"
    "- Keep the answer concise: lead with the direct answer, then the supporting table or breakdown.\n"
    "- Respond in the same language as the user's query."
)

_EVALUATE_COVERAGE_V2 = (
    "Decide whether the given evidence excerpts are enough to answer the original query. Respond only with "
    'a JSON object: {"status": "sufficient" or "insufficient", "missing_information": [array of short '
    'strings describing what is missing, empty if sufficient], "reasoning": short string}.\n\n'
    "If the query asks for a count, sum, average, or other computation over items already listed in the "
    "excerpts (e.g. rows, documents, entries), treat that as sufficient as soon as the raw items are present "
    "- the answer does not need to already be spelled out as a sentence, it can be computed from what's "
    "there. Only mark it insufficient if the underlying items themselves are missing."
)

_VALIDATE_GROUNDING_V2 = (
    "Check whether every important factual claim in the answer is supported by the given evidence "
    'excerpts. Respond only with a JSON object: {"valid": bool, "unsupported_claims": [array of short '
    "strings quoting or paraphrasing each unsupported claim, empty if valid]}.\n\n"
    "A claim that computes a count, sum, average, or other aggregate over items listed in the excerpts is "
    "supported as long as those underlying items are actually there - it does not need to appear as a "
    "pre-stated number in any single excerpt. Only flag it if the underlying items themselves are missing "
    "or the computation contradicts what's in the excerpts."
)

_UPDATED_PROMPTS = {
    "generate_answer": _GENERATE_ANSWER_V2,
    "evaluate_coverage": _EVALUATE_COVERAGE_V2,
    "validate_grounding": _VALIDATE_GROUNDING_V2,
}

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
    for name, content in _UPDATED_PROMPTS.items():
        current_version = conn.execute(
            sa.select(sa.func.max(_prompt_versions.c.version)).where(_prompt_versions.c.name == name)
        ).scalar_one()
        conn.execute(
            _prompt_versions.update()
            .where(_prompt_versions.c.name == name, _prompt_versions.c.is_active.is_(True))
            .values(is_active=False)
        )
        conn.execute(
            _prompt_versions.insert().values(
                id=uuid.uuid4(),
                name=name,
                version=current_version + 1,
                content=content,
                is_active=True,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    for name in _UPDATED_PROMPTS:
        max_version = conn.execute(
            sa.select(sa.func.max(_prompt_versions.c.version)).where(_prompt_versions.c.name == name)
        ).scalar_one()
        conn.execute(
            _prompt_versions.delete().where(_prompt_versions.c.name == name, _prompt_versions.c.version == max_version)
        )
        conn.execute(
            _prompt_versions.update()
            .where(_prompt_versions.c.name == name, _prompt_versions.c.version == max_version - 1)
            .values(is_active=True)
        )
