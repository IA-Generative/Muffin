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
from app.schemas.evaluation import EvaluationMetricsOut, EvaluationResultOut


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


# The namedScores keys the worker's tests write (its create_tests.py assertions) - keep in
# sync with worker/evaluation/app/promptfoo/create_tests.py. A metric missing from an old
# artifact (a run that predates context faithfulness) simply reads as None.
_METRICS = ("factuality", "context_faithfulness")


def _score(test: dict[str, Any], metric: str) -> float | None:
    named_scores = test.get("namedScores")
    if not isinstance(named_scores, dict):
        return None  # the judge errored on this pair - no score to average in
    value = named_scores.get(metric)
    return float(value) if isinstance(value, int | float) else None


def _average(tests: Sequence[dict[str, Any]], metric: str, golden: bool) -> float | None:
    scores = [
        score
        for test in tests
        if _coerce_bool(test.get("vars", {}).get("golden")) == golden and (score := _score(test, metric)) is not None
    ]
    # None on an empty subset, never 0.0 - a zero would read as a terrible score
    # where there is actually nothing to score (same rule as the old metric columns).
    return sum(scores) / len(scores) if scores else None


def metrics_from_tests(
    tests: Sequence[dict[str, Any]],
) -> tuple[EvaluationMetricsOut | None, EvaluationMetricsOut | None]:
    """(non-golden, golden) score averages - (None, None) when nothing was scored at all.
    A metric with no scores in the artifact (a run predating context faithfulness) stays
    None in its metrics object rather than dragging it to 0.0."""
    overall = {metric: _average(tests, metric, golden=False) for metric in _METRICS}
    golden = {metric: _average(tests, metric, golden=True) for metric in _METRICS}
    if all(score is None for score in (*overall.values(), *golden.values())):
        return None, None
    return (
        EvaluationMetricsOut(**overall) if any(score is not None for score in overall.values()) else None,
        EvaluationMetricsOut(**golden) if any(score is not None for score in golden.values()) else None,
    )


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
        factuality=_score(test, "factuality"),
        context_faithfulness=_score(test, "context_faithfulness"),
        validated=_coerce_bool(variables.get("validated")),
        golden=_coerce_bool(variables.get("golden")),
        retrieved_sources=metadata.get("sources") or [],
    )
