"""add prompt versioning

Revision ID: 4a5f9d2f6c06
Revises: b3c4d5e6f7a8
Create Date: 2026-09-21 14:57:50.118030

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4a5f9d2f6c06"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed data: the agent's 6 system prompts as they exist today as hardcoded Python constants
# (worker/agent_execution/app/graph/nodes/*.py) - copied verbatim as version 1, active, so this
# migration is a no-op behavior-wise. decompose_query/replan_research keep their {tool_names}/
# {guide} .format() placeholders (and, for replan_research, the escaped {{"query": ...}} JSON
# braces) exactly as in the source - the worker still calls .format() on whatever this table
# serves, versioned or fallback.
_SEED_PROMPTS: list[dict[str, str]] = [
    {
        "name": "analyze_query",
        "content": (
            "Analyze the user's current question, in light of the conversation so far if any is given. Respond only "
            'with a JSON object with keys: "intent" (one of "lookup", "comparison", "synthesis", "meta"), "topics" '
            '(array of short strings), "requires_multiple_sources" (bool), "complexity" (one of "simple", "complex"), '
            '"ambiguous" (bool - true only if the question is still unclear once the conversation history is taken '
            'into account), "clarification_question" (string or null, only set if ambiguous is true), '
            '"standalone_query" (string - the current question rewritten to stand on its own, resolving any pronoun '
            'or reference back to something said earlier in the conversation, e.g. "elle"/"it" -> the thing it '
            "refers to; if the question is already self-contained or there is no conversation history, repeat it "
            "unchanged).\n\n"
            'Use "meta" when the query is about the knowledge bases themselves rather than their content - e.g. '
            "how many collections/documents the user has access to, a collection's or document's summary, or the "
            "content/screenshot of one specific page, rather than a document/policy question that content search "
            "should answer.\n\n"
            'IMPORTANT - be very conservative with "ambiguous": only set it to true if the question is truly '
            "unanswerable without more information. The user has already selected one or more collections to query "
            'against, so references like "le fichier", "les données", "the data", "the file" are NOT ambiguous - '
            "they refer to the selected collection(s). Questions about columns, rows, averages, counts, sums, or "
            "any analytical operation on tabular data are NOT ambiguous even if they don't name a specific file. "
            "When in doubt, set ambiguous to false - it is better to attempt an answer than to block the user with "
            "a clarification question."
        ),
    },
    {
        "name": "decompose_query",
        "content": (
            "Break the user's query into research tasks. Respond only with a JSON array of objects with keys: "
            '"id" (short slug, unique), "query" (the question this task answers), "intent" (short string or null), '
            '"tool" (one of {tool_names}), '
            '"dependencies" (array of task ids this task needs completed first, e.g. a comparison task depends on '
            "the tasks covering each side of the comparison).\n\n"
            "{guide}\n"
            "A simple query stays a single task. Independent tasks must have an empty dependencies array so they can "
            "run in parallel."
        ),
    },
    {
        "name": "evaluate_coverage",
        "content": (
            "Decide whether the given evidence excerpts are enough to answer the original query. Respond only with "
            'a JSON object: {"status": "sufficient" or "insufficient", "missing_information": [array of short '
            'strings describing what is missing, empty if sufficient], "reasoning": short string}.'
        ),
    },
    {
        "name": "replan_research",
        "content": (
            "Coverage of a research query was judged insufficient. Given what's missing, produce only the new "
            "research tasks needed to fill those specific gaps - do not repeat searches already covered. Respond "
            'only with a JSON array of objects: {{"query": "...", "intent": "..." or null, "tool": {tool_names}}}.'
        ),
    },
    {
        "name": "validate_grounding",
        "content": (
            "Check whether every important factual claim in the answer is supported by the given evidence "
            'excerpts. Respond only with a JSON object: {"valid": bool, "unsupported_claims": [array of short '
            "strings quoting or paraphrasing each unsupported claim, empty if valid]}."
        ),
    },
    {
        "name": "generate_answer",
        "content": (
            "Answer the user's query using only the given evidence excerpts. Cite each claim with its excerpt id "
            "in brackets, e.g. [abc123]. Never invent facts not supported by the excerpts. If the evidence notes "
            "some information is missing, say so plainly instead of guessing or narrating your internal process. "
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
        ),
    },
]


def upgrade() -> None:
    """Upgrade schema."""
    prompt_versions = op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
    )
    op.create_index(op.f("ix_prompt_versions_name"), "prompt_versions", ["name"], unique=False)

    op.create_table(
        "run_prompt_usages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_run_prompt_usages_prompt_version_id"), "run_prompt_usages", ["prompt_version_id"], unique=False
    )
    op.create_index(op.f("ix_run_prompt_usages_run_id"), "run_prompt_usages", ["run_id"], unique=False)

    op.bulk_insert(
        prompt_versions,
        [
            {
                "id": uuid.uuid4(),
                "name": prompt["name"],
                "version": 1,
                "content": prompt["content"],
                "is_active": True,
            }
            for prompt in _SEED_PROMPTS
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_run_prompt_usages_run_id"), table_name="run_prompt_usages")
    op.drop_index(op.f("ix_run_prompt_usages_prompt_version_id"), table_name="run_prompt_usages")
    op.drop_table("run_prompt_usages")
    op.drop_index(op.f("ix_prompt_versions_name"), table_name="prompt_versions")
    op.drop_table("prompt_versions")
