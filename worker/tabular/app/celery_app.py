from celery import Celery
from kombu import Exchange, Queue

from app.config import settings

celery_app = Celery("muffin_tabular", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery_app.conf.update(
    task_default_queue=settings.SQL_QUEUE_NAME,
    # With its own exchange and routing key, as the sender declares and sends to it.
    task_queues=(
        Queue(settings.SQL_QUEUE_NAME, Exchange(settings.SQL_QUEUE_NAME), routing_key=settings.SQL_QUEUE_NAME),
    ),
    task_soft_time_limit=settings.SQL_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_acks_late=True,
    broker_transport_options={"visibility_timeout": settings.BROKER_VISIBILITY_TIMEOUT_SECONDS},
    worker_prefetch_multiplier=1,
    # Short: a result is read within seconds, and it holds rows of a user's data.
    result_expires=60 * 60,
    task_track_started=True,
)

from app import tasks  # noqa: E402,F401
