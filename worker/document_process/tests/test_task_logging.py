"""Each task's lines, sent to the backend as it runs (#305)."""

import logging
import threading
import uuid
from unittest.mock import MagicMock

import httpx
import pytest
from loguru import logger

from app import task_logging
from app.celery_app import celery_app

DOCUMENT_ID = str(uuid.uuid4())


@celery_app.task(name="tests.log_some_lines", bind=True)
def log_some_lines(self, document_id: str, fail: bool = False) -> None:
    logger.info("through loguru")
    logging.getLogger("some.library").warning("through the standard logging")
    logger.debug("below TASK_LOG_LEVEL")
    if fail:
        raise ValueError("it went wrong")


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(task_logging, "backend_client", backend)
    return backend


def _sent(backend: MagicMock) -> list[dict]:
    return [line for call in backend.add_task_logs.call_args_list for line in call.args[0]]


def test_a_tasks_lines_are_sent_with_its_task_and_document_by_the_end_of_it(backend):
    log_some_lines.apply(args=[DOCUMENT_ID], task_id="task-1")

    sent = [line for line in _sent(backend) if line["celery_task_id"] == "task-1"]
    messages = [line["message"] for line in sent]
    assert "through loguru" in messages
    assert "through the standard logging" in messages
    assert "below TASK_LOG_LEVEL" not in messages
    line = sent[messages.index("through loguru")]
    assert line["task_name"] == "tests.log_some_lines"
    assert line["document_id"] == DOCUMENT_ID
    assert line["level"] == "INFO"
    assert line["extra"]["function"] == "log_some_lines"
    # Celery's own line about how the task ended, too.
    assert any("succeeded" in message for message in messages)


def test_a_failed_tasks_traceback_is_sent(backend):
    log_some_lines.apply(args=[DOCUMENT_ID, True], task_id="task-2")

    errors = [line for line in _sent(backend) if line["celery_task_id"] == "task-2" and line["level"] == "ERROR"]
    assert any("ValueError: it went wrong" in line["message"] for line in errors)


def test_an_argument_that_is_not_an_id_is_left_out(backend):
    log_some_lines.apply(args=["not-an-id"], task_id="task-3")

    assert all(line["document_id"] is None for line in _sent(backend) if line["celery_task_id"] == "task-3")


def test_a_line_logged_outside_a_task_is_not_sent(backend):
    logger.info("starting up")
    task_logging._shipper.flush()

    assert all(line["message"] != "starting up" for line in _sent(backend))


def test_a_tasks_lines_are_only_its_own_in_a_pool_of_threads(backend):
    both_started = threading.Barrier(2)

    def run(task_id):
        task_logging._start_task(task_id=task_id, task=log_some_lines, args=(DOCUMENT_ID,))
        both_started.wait()
        logger.info(f"line of {task_id}")
        both_started.wait()
        task_logging._end_task()

    threads = [threading.Thread(target=run, args=(task_id,)) for task_id in ("task-a", "task-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for line in _sent(backend):
        if line["message"].startswith("line of"):
            assert line["message"] == f"line of {line['celery_task_id']}"


def test_lines_the_backend_could_not_take_are_sent_with_the_next_batch(backend):
    backend.add_task_logs.side_effect = [httpx.ConnectError("down"), None]
    task_logging._start_task(task_id="task-4", task=log_some_lines, args=(DOCUMENT_ID,))
    logger.info("while the backend is down")
    task_logging._end_task()

    task_logging._shipper.flush()

    assert any(line["message"] == "while the backend is down" for line in backend.add_task_logs.call_args.args[0])


def test_lines_the_backend_refuses_are_not_sent_again(backend):
    refused = httpx.HTTPStatusError("422", request=MagicMock(), response=MagicMock(status_code=422))
    backend.add_task_logs.side_effect = [refused, None]
    task_logging._start_task(task_id="task-5", task=log_some_lines, args=(DOCUMENT_ID,))
    logger.info("refused")
    task_logging._end_task()
    backend.add_task_logs.reset_mock()

    task_logging._shipper.flush()

    assert all(line["message"] != "refused" for line in _sent(backend))


def test_the_beat_purges_the_lines_past_their_retention_once_an_hour():
    entry = celery_app.conf.beat_schedule["purge-task-logs"]
    assert entry["task"] == "app.tasks.purge_task_logs"
    assert entry["schedule"].minute == {15}
