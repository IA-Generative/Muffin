"""Reads a run's promptfoo results.json artifact back out of RustFS - the source of
truth for everything scored in an evaluation run (see docs/promptfoo-evaluation-plan.md).
The scores are deliberately not copied into database columns: the artifact is written
once by the worker and read here at display time, so there is no second representation
to keep in sync."""

import json
from collections.abc import Sequence
from typing import Any

from loguru import logger

from app.core import storage
from app.models.evaluation import EvaluationRun
from app.schemas.evaluation import EvaluationResultOut


def load_tests(run: EvaluationRun) -> list[dict[str, Any]] | None:
    """The run's per-pair tests from its results.json artifact - None when the run has
    no artifact (it predates the promptfoo migration, or the upload never happened) or
    when the artifact can't be read/parsed: a display-time read must degrade to "no
    scores", never fail the whole evaluations listing."""
    if not run.results_json_key:
        return None
    try:
        data, _ = storage.get_object(run.results_json_key)
        return json.loads(data)["results"]["results"]
    except Exception:
        logger.exception(f"Failed to read evaluation artifacts for run {run.id}")
        return None


def _coerce_bool(value: Any) -> bool:
    # promptfoo echoes the test vars back as they were given, but a YAML round-trip
    # can turn a bool into "true"/"false" - accept both rather than trust one.
    return value is True or value == "true"


def _numeric_scores(test: dict[str, Any]) -> dict[str, float]:
    """The test's namedScores entries that hold a number - the metrics the judge
    actually scored for that pair. A metric the judge errored on writes no entry,
    and a non-numeric entry (promptfoo can emit strings) is ignored rather than
    averaged in."""
    named_scores = test.get("namedScores")
    if not isinstance(named_scores, dict):
        return {}  # the judge errored on this pair - no score to average in
    return {key: float(value) for key, value in named_scores.items() if isinstance(value, int | float)}


def _average(tests: Sequence[dict[str, Any]], metric: str, golden: bool) -> float | None:
    scores = [
        numeric[metric]
        for test in tests
        if _coerce_bool(test.get("vars", {}).get("golden")) == golden
        and (numeric := _numeric_scores(test)).get(metric) is not None
    ]
    # None on an empty subset, never 0.0 - a zero would read as a terrible score
    # where there is actually nothing to score (same rule as the old metric columns).
    return sum(scores) / len(scores) if scores else None


def metrics_from_tests(
    tests: Sequence[dict[str, Any]],
) -> tuple[dict[str, float] | None, dict[str, float] | None]:
    """(non-golden, golden) score averages keyed by metric name - (None, None) when
    nothing was scored at all. The keys are the union of whatever namedScores the
    artifact actually holds, so the worker's assertions alone decide what gets
    scored: a new metric flows through with zero backend change, and a run that
    predates a metric simply doesn't list it (absent key, never a 0.0 average)."""
    metrics = sorted({key for test in tests for key in _numeric_scores(test)})
    overall = {metric: average for metric in metrics if (average := _average(tests, metric, golden=False)) is not None}
    golden = {metric: average for metric in metrics if (average := _average(tests, metric, golden=True)) is not None}
    return overall or None, golden or None


def _passed(test: dict[str, Any]) -> bool:
    """Whether promptfoo marked the test as passed: every assertion scored at or above
    its threshold. A test the judge errored on carries no `success` and counts as not
    passed."""
    return test.get("success") is True


def golden_pass_rate(tests: Sequence[dict[str, Any]]) -> float | None:
    """The share of golden (test) pairs that passed, in [0, 1] - None when the run has
    no golden pair (nothing to rate, never a misleading 0)."""
    golden = [test for test in tests if _coerce_bool(test.get("vars", {}).get("golden"))]
    if not golden:
        return None
    return sum(_passed(test) for test in golden) / len(golden)


def to_result_out(test: dict[str, Any]) -> EvaluationResultOut:
    """Normalizes one promptfoo test into the shape the evaluations UI consumes -
    the mapping is kept here so a promptfoo format change only touches this module."""
    variables = test.get("vars") or {}
    response = test.get("response") or {}
    output = response.get("output") or {}
    metadata = response.get("metadata") or {}
    qa_pair_id = variables.get("qa_pair_id")
    return EvaluationResultOut(
        qa_pair_id=str(qa_pair_id) if qa_pair_id else None,
        # `query` since promptfoo's RAG assertions require that var name; `question` is
        # the pre-rename spelling, kept for artifacts of runs that predate it.
        question=variables.get("query") or variables.get("question") or "",
        expected_answer=variables.get("reference") or "",
        generated_answer=output.get("answer") or "",
        named_scores=_numeric_scores(test),
        validated=_coerce_bool(variables.get("validated")),
        golden=_coerce_bool(variables.get("golden")),
        retrieved_sources=metadata.get("sources") or [],
    )
