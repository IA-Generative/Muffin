from celery import Celery
from kombu import Exchange, Queue

from app.config import settings

celery_app = Celery("muffin_ocr", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.OCR_QUEUE_NAME,
    # With its own exchange and routing key, as the extraction worker declares and sends to it.
    task_queues=(
        Queue(settings.OCR_QUEUE_NAME, Exchange(settings.OCR_QUEUE_NAME), routing_key=settings.OCR_QUEUE_NAME),
    ),
    task_soft_time_limit=settings.OCR_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_acks_late=True,
    broker_transport_options={"visibility_timeout": settings.BROKER_VISIBILITY_TIMEOUT_SECONDS},
    worker_prefetch_multiplier=1,
    # Must match the extraction worker's, for one lifetime of a task's history.
    result_expires=60 * 60 * 24 * 7,
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
