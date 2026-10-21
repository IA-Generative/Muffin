from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import settings

celery_app = Celery("muffin_document_process", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

# Which queue - so which pod - runs each task (#291). Extraction is CPU-bound and runs a few at a time;
# enrichment mostly waits for the embeddings/LLM API and runs many at once; an import or a rebuild is
# long I/O that must hold up neither. A task spawned by another one lands on its own queue, whatever
# the queue of the task that spawned it.
_EXTRACTION_TASKS = (
    "app.tasks.process_document",
    "app.tasks.process_tabular_document",
    "app.tasks.refresh_url_document",
    "app.tasks.scan_url_refresh",
)
_ENRICHMENT_TASKS = (
    "app.tasks.chunk_document",
    "app.tasks.summarize_document",
    "app.tasks.generate_qa_window",
    "app.tasks.extract_entities_window",
    "app.tasks.tag_document",
    "app.tasks.update_collection_description",
    "app.tasks.update_collection_tags",
    "app.tasks.rollup_collection_description",
    "app.tasks.generate_collection_qa",
)

celery_app.conf.update(
    task_default_queue=settings.EXTRACTION_QUEUE_NAME,
    # Each with its own exchange and routing key, as the backend declares them when it sends a task:
    # a bare Queue(name) would be bound to the default queue's exchange and routing key instead.
    task_queues=tuple(
        Queue(name, Exchange(name), routing_key=name)
        for name in (
            settings.EXTRACTION_QUEUE_NAME,
            settings.ENRICHMENT_QUEUE_NAME,
            settings.IMPORT_QUEUE_NAME,
            settings.REBUILD_QUEUE_NAME,
            settings.LEGACY_QUEUE_NAME,
        )
    ),
    task_routes={
        **{name: {"queue": settings.EXTRACTION_QUEUE_NAME} for name in _EXTRACTION_TASKS},
        **{name: {"queue": settings.ENRICHMENT_QUEUE_NAME} for name in _ENRICHMENT_TASKS},
        "app.tasks.import_zip": {"queue": settings.IMPORT_QUEUE_NAME},
        "app.tasks.rebuild_index": {"queue": settings.REBUILD_QUEUE_NAME},
    },
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
    # Run by the beat embedded in the extraction worker only (`-B`, see docker-compose.yaml and the
    # Helm values): one scan per pod running it.
    beat_schedule={
        "scan-url-refresh": {
            "task": "app.tasks.scan_url_refresh",
            "schedule": crontab(minute=settings.URL_REFRESH_SCAN_MINUTES),
            "options": {"queue": settings.EXTRACTION_QUEUE_NAME},
        }
    },
)

from app import tasks  # noqa: E402,F401
