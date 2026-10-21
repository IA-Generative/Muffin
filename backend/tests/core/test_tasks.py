from unittest.mock import patch

from app.core import tasks


def test_enqueue_edit_document_sends_the_payload_to_the_document_edit_queue():
    payload = {"source_storage_key": "documents/c/a.odt", "prompt": "x", "document_id": "d", "base_revision": 1}

    with patch.object(tasks._celery_app, "send_task") as send_task:
        send_task.return_value.id = "celery-id"
        task_id = tasks.enqueue_edit_document(payload)

    assert task_id == "celery-id"
    send_task.assert_called_once_with("app.tasks.edit_document", args=[payload], queue="document_edit", task_id=None)


def test_the_edit_and_image_jobs_run_under_the_id_the_caller_chose():
    with patch.object(tasks._celery_app, "send_task") as send_task:
        send_task.return_value.id = "chosen"
        tasks.enqueue_edit_document({"x": 1}, task_id="chosen")
        tasks.enqueue_insert_images({"y": 2}, task_id="chosen")

    edit, images = send_task.call_args_list
    assert edit.args == ("app.tasks.edit_document",) and edit.kwargs["task_id"] == "chosen"
    assert images.args == ("app.tasks.insert_images",) and images.kwargs["queue"] == "document_edit"
    assert images.kwargs["task_id"] == "chosen"


def test_enqueue_rebuild_index_uses_its_own_queue_apart_from_ingestion():
    with patch.object(tasks._celery_app, "send_task") as send_task:
        send_task.return_value.id = "celery-id"
        task_id = tasks.enqueue_rebuild_index("rebuild-1")

    assert task_id == "celery-id"
    send_task.assert_called_once_with("app.tasks.rebuild_index", args=["rebuild-1"], queue="index_rebuild")
    assert tasks.INDEX_REBUILD_QUEUE != tasks.DOCUMENT_PROCESSING_QUEUE
