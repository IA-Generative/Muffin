"""Each task's lifecycle, reported to the backend as it runs."""

from unittest.mock import MagicMock

import pytest

from app import task_status
from app.celery_app import celery_app


@celery_app.task(name="tests.status_ok")
def status_ok() -> str:
    return "ok"


@celery_app.task(name="tests.status_fails")
def status_fails() -> None:
    raise ValueError("it went wrong")


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(task_status, "backend_client", backend)
    return backend


def _reported(backend: MagicMock) -> list[tuple[str, str, str | None]]:
    return [
        (call.args[0], call.args[1], call.args[2] if len(call.args) > 2 else None)
        for call in backend.update_task_status.call_args_list
    ]


def test_a_task_reports_started_then_success(backend):
    status_ok.apply(task_id="task-1")

    assert _reported(backend) == [("task-1", "STARTED", None), ("task-1", "SUCCESS", None)]


def test_a_failed_task_reports_its_exception(backend):
    status_fails.apply(task_id="task-2")

    reported = _reported(backend)
    assert reported[0] == ("task-2", "STARTED", None)
    assert reported[-1][:2] == ("task-2", "FAILURE")
    assert "it went wrong" in reported[-1][2]


def test_a_task_the_backend_could_not_be_told_about_still_runs(backend):
    backend.update_task_status.side_effect = RuntimeError("down")

    assert status_ok.apply(task_id="task-3").get() == "ok"


def test_the_beat_reaps_the_stuck_tasks_once_an_hour():
    entry = celery_app.conf.beat_schedule["reap-stuck-tasks"]
    assert entry["task"] == "app.tasks.reap_stuck_tasks"
    assert entry["schedule"].minute == {45}
