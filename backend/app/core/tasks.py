from celery import Celery

from app.config import RedisSettings

_redis_settings = RedisSettings()
_celery_app = Celery("muffin_backend_producer", broker=_redis_settings.REDIS_URL)

# Must match worker/document_process/app/celery_app.py's queue and task name
# exactly - the backend only produces this task, it never imports the
# worker's code (separate service, separate deploy).
DOCUMENT_PROCESSING_QUEUE = "document_processing"
PROCESS_DOCUMENT_TASK = "app.tasks.process_document"


def enqueue_process_document(document_id: str) -> None:
    _celery_app.send_task(PROCESS_DOCUMENT_TASK, args=[document_id], queue=DOCUMENT_PROCESSING_QUEUE)
