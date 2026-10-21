from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.celery_app import celery_app
from app.config import settings
from app.tasks import rebuild


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(rebuild.time, "sleep", lambda seconds: None)
    fake.embed_batch.side_effect = lambda model, texts: [[0.1, 0.2] for _ in texts]
    return fake


def _point(point_id: str, text: str = "text") -> dict:
    return {"id": point_id, "kind": "chunk", "text": text}


def _plan(status: str, points: list[dict], remaining: int | None = None) -> dict:
    return {
        "status": status,
        "collection_id": "col-1",
        "model": "new-model",
        "points": points,
        "remaining": len(points) if remaining is None else remaining,
    }


def test_the_rebuild_has_its_own_queue_apart_from_ingestion():
    assert celery_app.conf.task_routes["app.tasks.rebuild_index"] == {"queue": settings.REBUILD_QUEUE_NAME}
    assert settings.REBUILD_QUEUE_NAME not in (settings.EXTRACTION_QUEUE_NAME, settings.ENRICHMENT_QUEUE_NAME)


def test_the_rebuild_is_not_killed_by_the_ingestion_time_limit():
    assert tasks.rebuild_index.time_limit > celery_app.conf.task_time_limit


def test_it_embeds_what_the_plan_lists_with_the_plans_model_then_swaps(backend):
    backend.get_rebuild_plan.side_effect = [
        _plan("building", [_point("a", "one"), _point("b", "two")]),
        _plan("building", []),
        _plan("swapped", []),
    ]

    result = tasks.rebuild_index("rb-1")

    assert result == "swapped"
    backend.embed_batch.assert_called_once_with("new-model", ["one", "two"])
    stored = backend.submit_rebuild_vectors.call_args.args
    assert stored[:2] == ("rb-1", "new-model")
    assert [point["id"] for point in stored[2]] == ["a", "b"]
    assert stored[2][0]["embedding"] == [0.1, 0.2] and stored[2][0]["text"] == "one"
    backend.swap_rebuild.assert_called_once_with("rb-1")
    backend.fail_rebuild.assert_not_called()


def test_it_carries_on_when_the_swap_finds_points_added_since(backend):
    backend.get_rebuild_plan.side_effect = [
        _plan("building", []),
        _plan("building", [_point("late")]),
        _plan("building", []),
        _plan("swapped", []),
    ]

    tasks.rebuild_index("rb-1")

    assert backend.swap_rebuild.call_count == 2
    assert [point["id"] for point in backend.submit_rebuild_vectors.call_args.args[2]] == ["late"]


def test_the_points_go_to_the_hub_in_batches(backend, monkeypatch):
    monkeypatch.setattr(rebuild, "EMBED_BATCH", 2)
    backend.get_rebuild_plan.side_effect = [
        _plan("building", [_point(str(index)) for index in range(5)]),
        _plan("building", []),
        _plan("swapped", []),
    ]

    tasks.rebuild_index("rb-1")

    assert [len(call.args[1]) for call in backend.embed_batch.call_args_list] == [2, 2, 1]
    assert backend.submit_rebuild_vectors.call_count == 3


def test_a_swapped_rebuild_is_done_once_its_last_plan_is_empty(backend):
    # After the swap the job reconciles the new active index once, then stops - it never swaps again.
    backend.get_rebuild_plan.side_effect = [_plan("swapped", [_point("gap")]), _plan("swapped", [])]

    result = tasks.rebuild_index("rb-1")

    assert result == "swapped"
    backend.swap_rebuild.assert_not_called()
    assert backend.submit_rebuild_vectors.call_count == 1


def test_a_finished_rebuild_has_nothing_left_to_do(backend):
    backend.get_rebuild_plan.return_value = _plan("finalized", [])

    assert tasks.rebuild_index("rb-1") == "finalized"

    backend.embed_batch.assert_not_called()
    backend.swap_rebuild.assert_not_called()


def test_a_hiccup_is_retried_without_failing_the_rebuild(backend):
    backend.get_rebuild_plan.side_effect = [
        _plan("building", [_point("a")]),
        _plan("building", []),
        _plan("swapped", []),
    ]
    backend.embed_batch.side_effect = [RuntimeError("hub timeout"), [[0.1]]]

    assert tasks.rebuild_index("rb-1") == "swapped"

    assert backend.embed_batch.call_count == 2
    backend.fail_rebuild.assert_not_called()


def test_a_lasting_failure_is_reported_so_the_lock_is_freed(backend):
    backend.get_rebuild_plan.return_value = _plan("building", [_point("a")])
    backend.embed_batch.side_effect = RuntimeError("hub is down")

    with pytest.raises(RuntimeError, match="hub is down"):
        tasks.rebuild_index("rb-1")

    backend.fail_rebuild.assert_called_once_with("rb-1", "hub is down")
