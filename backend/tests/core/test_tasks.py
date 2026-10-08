from unittest.mock import patch

from app.core import tasks


def test_enqueue_edit_document_sends_the_payload_to_the_document_edit_queue():
    payload = {"source_storage_key": "documents/c/a.odt", "prompt": "x", "document_id": "d", "base_revision": 1}

    with patch.object(tasks._celery_app, "send_task") as send_task:
        send_task.return_value.id = "celery-id"
        task_id = tasks.enqueue_edit_document(payload)

    assert task_id == "celery-id"
    send_task.assert_called_once_with("app.tasks.edit_document", args=[payload], queue="document_edit")
