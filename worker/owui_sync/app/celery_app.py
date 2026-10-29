from celery import Celery

from app import (  # noqa: F401 - loguru everywhere, each task's lines (#305) and its time, CPU and memory, to the backend
    execution_metrics,
    task_logging,
)
from app.config import settings
from app.task_revocation import RevocableTask

celery_app = Celery("muffin_owui_sync", broker=settings.REDIS_URL, backend=settings.REDIS_URL, task_cls=RevocableTask)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE_NAME,
    task_routes={"app.tasks.*": {"queue": settings.CELERY_QUEUE_NAME}},
    task_acks_late=True,
    # Many small tasks (#453): one at a time per slot, so that a slow collection never holds back the others.
    worker_prefetch_multiplier=1,
    # Must match backend/app/core/tasks.py's for a consistent task history lifetime.
    result_expires=60 * 60 * 24 * 7,
    task_track_started=True,
    # Run by the beat only: a worker started without it never schedules anything.
    beat_schedule=(
        {
            "sync-owui": {
                "task": "app.tasks.sync_owui",
                "schedule": settings.OWUI_SYNC_INTERVAL_MINUTES * 60,
                "options": {"queue": settings.CELERY_QUEUE_NAME},
            }
        }
        if settings.OWUI_SYNC_INTERVAL_MINUTES > 0
        else {}
    ),
)

from app import tasks  # noqa: E402,F401
