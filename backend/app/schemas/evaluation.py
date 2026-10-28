import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EvaluationTriggerRequest(BaseModel):
    # How many chunks the worker retrieves per question - same meaning as any other search's
    # `limit` (see worker/agent_execution's MAX_PARALLEL_SEARCHES-style budgets), just for the
    # evaluation's own retrieval pass rather than a live agent run.
    k: int = 5
    # When True (default), only validated QA pairs are evaluated. When False, all QA pairs
    # with a source document are evaluated - lets the user run evaluation on unvalidated
    # pairs too (the validated/unvalidated breakdown in EvaluationRun still separates them).
    validated_only: bool = False


class EvaluationStatusOut(BaseModel):
    """Whether an evaluation is currently queued or running for a collection - lets the UI
    restore its in-progress state after a reload (see EvaluationService.is_running)."""

    running: bool


class EvaluationRunOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    created_at: datetime
    pair_count: int
    # The judge model (the collection's "evaluation" generation model).
    llm_model: str
    # The golden (test) pairs, scored apart - the numbers to follow over time.
    golden_pair_count: int = 0
    validated_pair_count: int
    unvalidated_pair_count: int
    # SHA-256 of (QA pairs + chunking settings + embedding model + k + judge model + generator
    # model + scored metrics) - present when the worker computed it for dedup (see
    # EvaluationRun.content_hash).
    content_hash: str | None = None
    # Score averages over the reference (non-golden) / golden / every pair, keyed by metric
    # name - the keys are whatever the run's artifact actually scored (the worker's assertions
    # decide, see worker/evaluation/app/promptfoo/create_tests.py), so a new metric
    # flows through with zero backend change. None when that subset is empty, when
    # nothing was scored, or when the run predates the promptfoo migration (no
    # artifact) - a metric a run predates simply doesn't appear in its dict.
    metrics: dict[str, float] | None
    golden_metrics: dict[str, float] | None
    all_metrics: dict[str, float] | None
    # The share of golden (test) pairs that passed (every assertion at or above its
    # threshold), in [0, 1] - None when the run has no golden pair or no artifact.
    golden_pass_rate: float | None = None
    # The same share over the reference (non-golden) pairs, and over every pair of the
    # run - each None when its subset is empty or the run has no artifact.
    reference_pass_rate: float | None = None
    overall_pass_rate: float | None = None
    # Whether the report/results.json artifacts exist (download links, report preview) -
    # False on the runs predating the promptfoo migration.
    has_artifacts: bool
    # The worker's config_muffin block, replayed into results.json (see tasks.py's
    # EvaluationConfig.config_muffin): the run's whole configuration, shown as-is under the
    # UI's "Détails techniques". None when the run has no readable artifact.
    config_muffin: dict[str, Any] | None = None
