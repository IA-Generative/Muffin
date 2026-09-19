"""Schemas for the cross-collection Quality dashboard (see #33).

Aggregates four metric families into one response:
- retrieval: latest EvaluationRun aggregates per collection (see #11)
- feedback: thumbs up/down counts and reason breakdown (see #30)
- discussion: LLM-generated DiscussionScore aggregates (see #31)
- groundedness: Run.grounding_valid aggregates (see #32)

When `collection_id` is None, the admin sees all collections aggregated together.
When set, only that collection's metrics are returned (same data as the per-collection
tabs, but in one call).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RetrievalMetricOut(BaseModel):
    """Snapshot of the latest evaluation run's global aggregates."""

    collection_id: UUID
    collection_name: str
    run_id: UUID
    created_at: datetime
    pair_count: int
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg: float


class FeedbackMetricOut(BaseModel):
    up_count: int
    down_count: int
    reason_counts: dict[str, int]


class DiscussionMetricOut(BaseModel):
    """Aggregates over all DiscussionScore rows in scope."""

    total_conversations: int
    coherent_count: int
    avg_context_usage_score: float | None
    avg_rating: float | None


class GroundednessMetricOut(BaseModel):
    evaluated_count: int
    ungrounded_count: int


class DiscussionScoreEntry(BaseModel):
    """A single LLM discussion score for a conversation — one row per (model, content_hash)."""

    id: UUID
    created_at: datetime
    llm_model: str
    message_count: int
    coherent: bool
    context_usage_score: float


class ConversationWithScoreOut(BaseModel):
    """A conversation with its latest discussion score and human feedback, for the
    'discussions' section of the quality page.

    `scores` contains ALL scores for this conversation (across all models),
    sorted by creation date descending. The top-level `coherent`,
    `context_usage_score`, and `llm_model` fields mirror the first entry in
    `scores` (the latest) for backward compatibility."""

    id: UUID
    title: str | None
    created_at: datetime
    message_count: int
    # LLM score (may be null if never scored) — mirrors scores[0] for convenience
    coherent: bool | None
    context_usage_score: float | None
    llm_model: str | None
    # All scores for this conversation (all models), latest first
    scores: list[DiscussionScoreEntry]
    # Human feedback (may be null if never submitted)
    human_rating: int | None
    human_coherent: bool | None


class QualityOverviewOut(BaseModel):
    """The full quality dashboard payload - one call, all families."""

    retrieval: list[RetrievalMetricOut]
    feedback: FeedbackMetricOut
    discussion: DiscussionMetricOut
    groundedness: GroundednessMetricOut
    conversations: list[ConversationWithScoreOut]
    conversations_total: int
    conversations_page: int
