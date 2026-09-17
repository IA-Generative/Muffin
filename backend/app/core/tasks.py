from celery import Celery
from celery.result import AsyncResult

from app.config import RedisSettings

_redis_settings = RedisSettings()
_celery_app = Celery("muffin_backend_producer", broker=_redis_settings.REDIS_URL, backend=_redis_settings.REDIS_URL)
# Celery's own default (1 day) would make a task's status silently fall back
# to PENDING once its result key expires, well before anyone looking at a
# task history would expect it to disappear.
_celery_app.conf.result_expires = 60 * 60 * 24 * 7

# Must match worker/document_process/app/celery_app.py's queue and task name
# exactly - the backend only produces this task, it never imports the
# worker's code (separate service, separate deploy).
DOCUMENT_PROCESSING_QUEUE = "document_processing"
PROCESS_DOCUMENT_TASK = "app.tasks.process_document"


def enqueue_process_document(document_id: str) -> str:
    """Returns the Celery task id, so the caller can record it (see
    app/models/task.py) for later status lookups and revocation."""
    result = _celery_app.send_task(PROCESS_DOCUMENT_TASK, args=[document_id], queue=DOCUMENT_PROCESSING_QUEUE)
    return result.id


def get_task_status(celery_task_id: str) -> str:
    return AsyncResult(celery_task_id, app=_celery_app).status


def revoke_task(celery_task_id: str) -> None:
    _celery_app.control.revoke(celery_task_id, terminate=True)
