"""A task the user revoked stays revoked, and stops wherever it runs."""

from unittest.mock import MagicMock

import pytest

from app import task_logging, task_revocation, tasks, usage_context
from app.celery_app import celery_app
from app.task_revocation import TaskRevoked, raise_if_revoked

ran = []


@celery_app.task(name="tests.revocable")
def revocable(label: str = "x") -> str:
    ran.append(label)
    return label


@celery_app.task(name="tests.revocable_in_two_steps")
def in_two_steps() -> None:
    ran.append("first step")
    raise_if_revoked()
    ran.append("second step")


@pytest.fixture(autouse=True)
def _fresh():
    ran.clear()
    yield
    # Running a task with apply() sets the context variables of this test's thread: not for the next.
    usage_context._usage.set(None)
    task_revocation._running.set(None)
    task_logging._task.set(None)


@pytest.fixture
def revoked_flags(monkeypatch):
    """Which tasks have the flag in Redis - the answers to the question asked at each call."""
    answers = []
    monkeypatch.setattr(task_revocation, "_is_revoked", lambda app, task_id: answers.pop(0) if answers else False)
    monkeypatch.setattr(celery_app.backend, "mark_as_revoked", marks := MagicMock())
    return answers, marks


def test_a_task_nobody_revoked_runs(revoked_flags):
    assert revocable.apply(args=["a"]).get() == "a"
    assert ran == ["a"]


def test_a_task_revoked_before_it_starts_is_dropped_and_says_revoked(revoked_flags):
    answers, marks = revoked_flags
    answers.append(True)

    outcome = revocable.apply(args=["a"], task_id="t-1")

    assert ran == []
    assert not outcome.failed()
    # STARTED, written by track_started just before the task is dropped, is not what stays.
    marks.assert_called_once_with("t-1", reason="revoked by the user")


def test_a_task_revoked_while_it_runs_stops_at_the_next_step(revoked_flags):
    answers, _ = revoked_flags
    answers.extend([False, True])  # at its start, then at the step

    outcome = in_two_steps.apply(task_id="t-2")

    assert ran == ["first step"]
    assert not outcome.failed()


def test_a_task_runs_all_the_way_when_it_is_not_revoked_in_between(revoked_flags):
    in_two_steps.apply(task_id="t-3")

    assert ran == ["first step", "second step"]


def test_redis_not_answering_never_stops_a_task(monkeypatch):
    client = MagicMock()
    client.exists.side_effect = ConnectionError("Redis is down")
    monkeypatch.setattr(celery_app.backend, "client", client, raising=False)

    assert revocable.apply(args=["a"]).get() == "a"


def test_raise_if_revoked_outside_a_task_does_nothing():
    task_revocation._running.set(None)

    raise_if_revoked()


def test_the_flag_is_looked_up_under_the_key_the_backend_writes():
    assert task_revocation.REVOKED_KEY == "muffin:revoked:{task_id}"


# -- the pipeline's tasks ----------------------------------------------------------------------------


def test_an_llm_call_is_not_made_for_a_revoked_task(monkeypatch, revoked_flags):
    answers, _ = revoked_flags
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)

    @celery_app.task(name="tests.chat")
    def chat():
        tasks._shared._chat("model", "system", "question")

    answers.extend([False, True])
    chat.apply(task_id="t-4")

    backend.llm_chat.assert_not_called()


def test_a_revoked_chunking_does_not_fail_the_document(monkeypatch, revoked_flags):
    answers, _ = revoked_flags
    backend = MagicMock()
    backend.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "emb",
        "pipeline_windows": {},
    }
    backend.get_pages.return_value = [{"page_number": 1, "content": "Un.\n\nDeux."}]
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    answers.extend([False, True])  # at the start, then before the first chunk

    outcome = tasks.chunk_document.apply(args=["doc-1", "col-1"], task_id="t-5")

    assert not outcome.failed()
    backend.add_chunk.assert_not_called()
    # The backend marked the document cancelled; the worker must not say it failed, nor index it.
    backend.update_status.assert_not_called()
    backend.set_document_error.assert_not_called()


def test_a_revoked_task_is_not_reported_as_a_failure_of_its_document(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)

    tasks._shared._fail("doc-1", "summarize", TaskRevoked())

    backend.set_document_error.assert_not_called()


def test_an_ordinary_failure_is_still_reported(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)

    tasks._shared._fail("doc-1", "summarize", RuntimeError("boom"))

    backend.set_document_error.assert_called_once_with("doc-1", "boom")


def test_every_task_of_the_worker_is_built_on_the_revocable_class():
    assert issubclass(celery_app.Task, task_revocation.RevocableTask)
