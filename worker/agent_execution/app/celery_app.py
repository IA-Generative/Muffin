from celery import Celery

from app.config import settings

celery_app = Celery("muffin_agent_execution", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE_NAME,
    task_routes={"app.tasks.run_agent": {"queue": settings.CELERY_QUEUE_NAME}},
    # A run can legitimately take a while (multiple LLM calls, several
    # searches) - generous compared to document_process's fixed-size jobs,
    # revisited once real multi-task fan-out lands (§13).
    task_time_limit=900,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Must match backend/app/core/tasks.py's for a consistent run history
    # lifetime - this worker is the one that actually stores the result.
    result_expires=60 * 60 * 24 * 7,
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
