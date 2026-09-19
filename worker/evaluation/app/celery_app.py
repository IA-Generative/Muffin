from celery import Celery

from app.config import settings

celery_app = Celery("muffin_evaluation", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE_NAME,
    task_routes={
        "app.tasks.run_evaluation": {"queue": settings.CELERY_QUEUE_NAME},
        "app.tasks.score_discussion": {"queue": settings.CELERY_QUEUE_NAME},
    },
    # An evaluation replays every validated QA pair of a collection through search + generation -
    # potentially long for a large collection, so no hard time limit like document_process's
    # (corrupt-file parsing isn't interruptible; this is just a lot of ordinary LLM calls).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Must match backend/app/core/tasks.py's for a consistent task history lifetime.
    result_expires=60 * 60 * 24 * 7,
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
