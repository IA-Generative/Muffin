"""Reads a run's promptfoo results.json artifact back out of RustFS - the source of
truth for everything scored in an evaluation run.
The scores are deliberately not copied into database columns: the artifact is written
once by the worker and read here at display time, so there is no second representation
to keep in sync.

The artifact is promptfoo's own format, so it is parsed into the small pydantic model
below rather than read as loose dicts: the model names the fields the backend actually
uses, and `extra="ignore"` keeps a promptfoo schema addition from breaking the read.
Only what the backend reads is modelled - the artifact holds far more (grading detail,
token usage, the whole config), none of it used here.
"""

import asyncio
import json
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import storage
from app.models.evaluation import EvaluationRun


def _coerce_bool(value: Any) -> bool:
    # promptfoo echoes the test vars back as they were given, but a YAML round-trip
    # can turn a bool into "true"/"false" - accept both rather than trust one.
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


class TestVars(BaseModel):
    """The vars promptfoo echoes back for one test - only the scope the backend reads."""

    model_config = ConfigDict(extra="ignore")

    golden: bool = False

    @field_validator("golden", mode="before")
    @classmethod
    def _bool_from_var(cls, value: Any) -> bool:
        return _coerce_bool(value)


class EvaluationTest(BaseModel):
    """One promptfoo test result, as the backend reads it back from results.json."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    vars: TestVars = Field(default_factory=TestVars)
    named_scores: dict[str, float] = Field(default_factory=dict, alias="namedScores")
    success: bool = False

    @field_validator("named_scores", mode="before")
    @classmethod
    def _numeric_scores_only(cls, value: Any) -> dict[str, float]:
        # A metric the judge errored on writes no entry at all, and promptfoo can emit a
        # non-numeric namedScore (a string) - ignore those rather than average them in.
        if not isinstance(value, dict):
            return {}
        return {key: float(score) for key, score in value.items() if isinstance(score, int | float)}


class EvaluationArtifact(BaseModel):
    """A run's results.json, as the backend reads it back: the per-pair tests and the
    config_muffin block the worker replayed into it (see tasks.py's config_muffin)."""

    model_config = ConfigDict(extra="ignore")

    tests: list[EvaluationTest] = Field(default_factory=list)
    config_muffin: dict[str, Any] | None = None


def _config_muffin(payload: dict[str, Any]) -> dict[str, Any] | None:
    # promptfoo replays the whole config into results.json, so the worker's block rides in
    # config.metadata.config_muffin (a top-level metadata.config_muffin on some versions).
    for container in (payload.get("config"), payload.get("metadata")):
        if isinstance(container, dict):
            metadata = container.get("metadata", container)
            if isinstance(metadata, dict) and isinstance(metadata.get("config_muffin"), dict):
                return metadata["config_muffin"]
    return None


# The parsed artifacts are cached by RustFS key: the artifact is written once and never
# overwritten (the key is evaluations/{run_id}/results.json), so a cached parse can't go
# stale. Bounded so a long-lived process can't grow without limit.
_ARTIFACT_CACHE_SIZE = 128


@lru_cache(maxsize=_ARTIFACT_CACHE_SIZE)
def _read_artifact(key: str) -> EvaluationArtifact:
    """Reads and parses one results.json - blocking network I/O, so callers run it off the
    event loop (asyncio.to_thread). Raises on a read/parse failure so the failure is never
    cached: a transient RustFS outage must not pin a run to "no scores" for ever."""
    data, _ = storage.get_object(key)
    payload = json.loads(data)
    raw = payload["results"]["results"]
    return EvaluationArtifact(
        tests=[EvaluationTest.model_validate(test) for test in raw],
        config_muffin=_config_muffin(payload),
    )


def clear_cache() -> None:
    """Drops the parsed-artifact cache. For tests, which reuse one key with different content
    (production keys are unique per run, so a cached parse can never go stale)."""
    _read_artifact.cache_clear()


async def load_artifact(run: EvaluationRun) -> EvaluationArtifact | None:
    """The run's results.json artifact parsed into the fields the backend reads - None when
    the run has no artifact (it predates the promptfoo migration, or the upload never
    happened) or when the artifact can't be read/parsed: a display-time read must degrade to
    "no scores", never fail the whole evaluations listing. The blocking read runs in a thread
    (see _read_artifact) so it never stalls the event loop."""
    if not run.results_json_key:
        return None
    try:
        return await asyncio.to_thread(_read_artifact, run.results_json_key)
    except Exception:
        logger.exception(f"Failed to read evaluation artifacts for run {run.id}")
        return None


async def load_tests(run: EvaluationRun) -> list[EvaluationTest] | None:
    """The run's per-pair tests from its results.json artifact - None when there is no
    readable artifact (see load_artifact)."""
    artifact = await load_artifact(run)
    return artifact.tests if artifact else None


def _average(tests: Sequence[EvaluationTest], metric: str, golden: bool | None) -> float | None:
    """The metric's average over the tests of one subset: golden=True for the test
    questions, golden=False for the reference ones, golden=None for every pair."""
    scores = [
        test.named_scores[metric]
        for test in tests
        if (golden is None or test.vars.golden == golden) and metric in test.named_scores
    ]
    # None on an empty subset, never 0.0 - a zero would read as a terrible score
    # where there is actually nothing to score (same rule as the old metric columns).
    return sum(scores) / len(scores) if scores else None


def metrics_from_tests(
    tests: Sequence[EvaluationTest],
) -> tuple[dict[str, float] | None, dict[str, float] | None, dict[str, float] | None]:
    """(reference, golden, all) score averages keyed by metric name - each None when
    nothing was scored over that subset. The keys are the union of whatever namedScores
    the artifact actually holds, so the worker's assertions alone decide what gets
    scored: a new metric flows through with zero backend change, and a run that
    predates a metric simply doesn't list it (absent key, never a 0.0 average)."""
    metrics = sorted({key for test in tests for key in test.named_scores})

    def averages(golden: bool | None) -> dict[str, float] | None:
        scored = {metric: average for metric in metrics if (average := _average(tests, metric, golden)) is not None}
        return scored or None

    return averages(golden=False), averages(golden=True), averages(golden=None)


def _passed(test: EvaluationTest) -> bool:
    """Whether promptfoo marked the test as passed: every assertion scored at or above
    its threshold. A test the judge errored on carries no `success` and counts as not
    passed."""
    return test.success is True


def _pass_rate(tests: Sequence[EvaluationTest]) -> float | None:
    """The share of tests promptfoo marked as passed, in [0, 1] - None on an empty
    subset (nothing to rate, never a misleading 0)."""
    if not tests:
        return None
    return sum(_passed(test) for test in tests) / len(tests)


def pass_rates(tests: Sequence[EvaluationTest]) -> tuple[float | None, float | None, float | None]:
    """(golden, reference, overall) pass rates - the share of test questions, of
    reference questions, and of every pair, that passed. Each is None when its subset
    is empty (a run with no golden pair has no golden rate, never a misleading 0)."""
    golden = [test for test in tests if test.vars.golden]
    reference = [test for test in tests if not test.vars.golden]
    return _pass_rate(golden), _pass_rate(reference), _pass_rate(tests)
