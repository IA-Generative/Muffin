import uuid
from unittest.mock import patch

from app.models.evaluation import EvaluationRun
from app.services import evaluation_artifacts

_RESULTS = (
    b'{"results": {"results": [{"vars": {"golden": true}, "namedScores": {"factuality": 1.0}, "success": true}]}}'
)


def _run(key: str = "evaluations/run/results.json") -> EvaluationRun:
    return EvaluationRun(id=uuid.uuid4(), results_json_key=key)


async def test_the_parsed_artifact_is_cached_by_key():
    run = _run()
    with patch("app.core.storage.get_object", return_value=(_RESULTS, "application/json")) as get_object:
        first = await evaluation_artifacts.load_artifact(run)
        second = await evaluation_artifacts.load_artifact(run)

    assert first is second
    get_object.assert_called_once_with(run.results_json_key)


async def test_a_failed_read_is_not_cached():
    run = _run()
    with patch(
        "app.core.storage.get_object",
        side_effect=[OSError("RustFS down"), (_RESULTS, "application/json")],
    ):
        assert await evaluation_artifacts.load_artifact(run) is None
        artifact = await evaluation_artifacts.load_artifact(run)

    assert artifact is not None
    assert artifact.tests[0].named_scores == {"factuality": 1.0}
