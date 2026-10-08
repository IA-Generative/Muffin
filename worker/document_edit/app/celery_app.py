from celery import Celery

from app.config import settings

celery_app = Celery("muffin_document_edit", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE_NAME,
    task_routes={"app.tasks.edit_document": {"queue": settings.CELERY_QUEUE_NAME}},
    # An edit job ends with a LibreOffice conversion, which can hang on a malformed document and
    # isn't interruptible - SIGKILL after the limit rather than stalling the queue, like
    # document_process does for a corrupt file.
    task_time_limit=600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Must match backend/app/core/tasks.py's for a consistent task history lifetime.
    result_expires=60 * 60 * 24 * 7,
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
