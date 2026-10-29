"""Which pod runs what (#291): every task of this image is routed to the queue of its kind of work."""

from pathlib import Path

import pytest

from app.celery_app import celery_app
from app.config import settings

EXTRACTION = [
    "app.tasks.process_document",
    "app.tasks.parse_page_range",
    "app.tasks.process_tabular_document",
    "app.tasks.refresh_url_document",
    "app.tasks.scan_url_refresh",
    "app.tasks.purge_task_logs",
    "app.tasks.reap_stuck_tasks",
    "app.tasks.release_import_queue",
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
    assert _queue_of("app.tasks.import_zip_batch") == settings.IMPORT_QUEUE_NAME
    assert _queue_of("app.tasks.rebuild_index") == settings.REBUILD_QUEUE_NAME


def test_every_task_of_the_image_has_a_route():
    """A new task without one would silently land on the default queue - the extraction pod's."""
    ours = {name for name in celery_app.tasks if name.startswith("app.tasks.")}
    assert ours == {
        *EXTRACTION,
        *ENRICHMENT,
        "app.tasks.import_zip",
        "app.tasks.import_zip_batch",
        "app.tasks.rebuild_index",
    }


def test_each_queue_has_its_own_exchange_and_routing_key():
    """As the backend declares them when it sends a task - not all bound to the default queue's."""
    for queue in celery_app.conf.task_queues:
        assert queue.exchange.name == queue.routing_key == queue.name


def test_the_image_starts_as_the_extraction_pod_with_the_beat():
    dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text()
    queues = f"{settings.EXTRACTION_QUEUE_NAME},{settings.LEGACY_QUEUE_NAME}"
    assert f'"-Q", "{queues}"' in dockerfile and '"-B"' in dockerfile


def test_the_ocr_pods_have_their_own_queues_that_the_backend_never_sends_to():
    from app.ocr import routing

    assert _queue_of(routing.LAYOUT_PAGE_TASK) == settings.LAYOUT_QUEUE_NAME == "document_layout"
    assert _queue_of(routing.OCR_REGIONS_TASK) == settings.OCR_QUEUE_NAME == "document_ocr"
    assert _queue_of(routing.TABLE_REGIONS_TASK) == settings.TABLE_QUEUE_NAME == "document_table"
    assert _queue_of(routing.DESCRIBE_REGIONS_TASK) == settings.VISION_QUEUE_NAME == "document_vision"


def test_the_ocr_queues_are_declared_so_this_worker_can_send_to_them():
    declared = {queue.name for queue in celery_app.conf.task_queues}
    assert {
        settings.LAYOUT_QUEUE_NAME,
        settings.OCR_QUEUE_NAME,
        settings.TABLE_QUEUE_NAME,
        settings.VISION_QUEUE_NAME,
    } <= declared


def test_the_extraction_pod_does_not_consume_the_ocr_queues():
    dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text()
    for name in (settings.LAYOUT_QUEUE_NAME, settings.OCR_QUEUE_NAME, settings.TABLE_QUEUE_NAME):
        assert name not in dockerfile
