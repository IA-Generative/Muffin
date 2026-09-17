from celery import Celery

from app.config import settings

celery_app = Celery("muffin_document_process", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE_NAME,
    task_routes={"app.tasks.process_document": {"queue": settings.CELERY_QUEUE_NAME}},
    # Rogue documents (corrupt PDFs, hung OCR) get killed instead of stalling
    # the queue - SIGKILL, not a graceful ask, since parsing isn't interruptible.
    task_time_limit=300,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # This worker is the one that actually stores the result, so it's this
    # setting (not the backend producer's) that sets the real Redis TTL -
    # must match app/core/tasks.py's on the backend for a consistent task
    # history lifetime.
    result_expires=60 * 60 * 24 * 7,
    # PENDING otherwise for a task's entire run, not just before a worker
    # picks it up - the backend's task list can't show "en cours" without this.
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
