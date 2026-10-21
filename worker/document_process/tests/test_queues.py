"""Which pod runs what (#291): every task of this image is routed to the queue of its kind of work."""

import threading
from pathlib import Path

import pytest
from loguru import logger

from app import task_logging
from app.celery_app import celery_app
from app.config import settings

EXTRACTION = [
    "app.tasks.process_document",
    "app.tasks.process_tabular_document",
    "app.tasks.refresh_url_document",
    "app.tasks.scan_url_refresh",
]
ENRICHMENT = [
    "app.tasks.chunk_document",
    "app.tasks.summarize_document",
    "app.tasks.generate_qa_window",
    "app.tasks.extract_entities_window",
    "app.tasks.tag_document",
    "app.tasks.update_collection_description",
    "app.tasks.update_collection_tags",
    "app.tasks.rollup_collection_description",
    "app.tasks.generate_collection_qa",
]


def _queue_of(task_name: str) -> str:
    return celery_app.amqp.router.route({}, task_name)["queue"].name


@pytest.mark.parametrize("task_name", EXTRACTION)
def test_extraction_runs_on_the_extraction_queue(task_name):
    assert _queue_of(task_name) == settings.EXTRACTION_QUEUE_NAME


@pytest.mark.parametrize("task_name", ENRICHMENT)
def test_embeddings_and_llm_calls_run_on_the_enrichment_queue(task_name):
    assert _queue_of(task_name) == settings.ENRICHMENT_QUEUE_NAME


def test_an_import_and_a_rebuild_run_on_their_own_queues():
    assert _queue_of("app.tasks.import_zip") == settings.IMPORT_QUEUE_NAME
    assert _queue_of("app.tasks.rebuild_index") == settings.REBUILD_QUEUE_NAME


def test_every_task_of_the_image_has_a_route():
    """A new task without one would silently land on the default queue - the extraction pod's."""
    ours = {name for name in celery_app.tasks if name.startswith("app.tasks.")}
    assert ours == {*EXTRACTION, *ENRICHMENT, "app.tasks.import_zip", "app.tasks.rebuild_index"}


def test_each_queue_has_its_own_exchange_and_routing_key():
    """As the backend declares them when it sends a task - not all bound to the default queue's."""
    for queue in celery_app.conf.task_queues:
        assert queue.exchange.name == queue.routing_key == queue.name


def test_the_image_starts_as_the_extraction_pod_with_the_beat():
    dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text()
    queues = f"{settings.EXTRACTION_QUEUE_NAME},{settings.LEGACY_QUEUE_NAME}"
    assert f'"-Q", "{queues}"' in dockerfile and '"-B"' in dockerfile


def test_a_tasks_logs_are_only_its_own_in_a_pool_of_threads(monkeypatch):
    reported = {}
    monkeypatch.setattr(
        task_logging.backend_client, "set_task_logs", lambda task_id, logs: reported.__setitem__(task_id, logs)
    )
    both_started = threading.Barrier(2)

    def task(task_id):
        with task_logging.capture_task_logs(task_id):
            both_started.wait()
            logger.info(f"line of {task_id}")
            both_started.wait()

    threads = [threading.Thread(target=task, args=(task_id,)) for task_id in ("task-a", "task-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert "line of task-a" in reported["task-a"] and "task-b" not in reported["task-a"]
    assert "line of task-b" in reported["task-b"] and "task-a" not in reported["task-b"]
