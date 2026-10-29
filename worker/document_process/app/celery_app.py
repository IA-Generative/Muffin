from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app import (  # noqa: F401 - loguru everywhere, each task's lines (#305) and its time, CPU and memory, to the backend
    execution_metrics,
    task_logging,
    task_status,
)
from app.config import settings
from app.ocr.routing import ocr_task_queues
from app.task_revocation import RevocableTask

celery_app = Celery(
    "muffin_document_process", broker=settings.REDIS_URL, backend=settings.REDIS_URL, task_cls=RevocableTask
)

# Which queue - so which pod - runs each task (#291). Extraction is CPU-bound and runs a few at a time;
# enrichment mostly waits for the embeddings/LLM API and runs many at once; an import or a rebuild is
# long I/O that must hold up neither. A task spawned by another one lands on its own queue, whatever
# the queue of the task that spawned it.
_EXTRACTION_TASKS = (
    "app.tasks.process_document",
    "app.tasks.parse_page_range",
    "app.tasks.process_tabular_document",
    "app.tasks.refresh_url_document",
    "app.tasks.scan_url_refresh",
    "app.tasks.purge_task_logs",
    "app.tasks.reap_stuck_tasks",
    "app.tasks.release_import_queue",
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
    "app.tasks.summarize_copied_document",
    "app.tasks.describe_copied_collection",
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
            # The OCR pods' (app/ocr/): this worker only sends to them.
            settings.LAYOUT_QUEUE_NAME,
            settings.OCR_QUEUE_NAME,
            settings.TABLE_QUEUE_NAME,
            settings.VISION_QUEUE_NAME,
        )
    ),
    task_routes={
        **{name: {"queue": settings.EXTRACTION_QUEUE_NAME} for name in _EXTRACTION_TASKS},
        **{name: {"queue": settings.ENRICHMENT_QUEUE_NAME} for name in _ENRICHMENT_TASKS},
        "app.tasks.import_zip": {"queue": settings.IMPORT_QUEUE_NAME},
        "app.tasks.import_zip_batch": {"queue": settings.IMPORT_QUEUE_NAME},
        "app.tasks.rebuild_index": {"queue": settings.REBUILD_QUEUE_NAME},
        **{name: {"queue": queue} for name, queue in ocr_task_queues().items()},
    },
    # No hard limit: a big document or archive is not killed for being big (#294). What can hang is
    # bounded where it happens - the parser's own timeout (app/parsing.py), HTTP and S3 timeouts - and
    # every task gets a soft limit as a safety net: an exception raised in it, so that it fails and
    # reports instead of being killed halfway. Only the prefork pods honour it (a pool of threads
    # cannot interrupt a task), where the tasks that can run long.
    task_soft_time_limit=settings.TASK_SOFT_TIME_LIMIT_SECONDS,
    task_acks_late=True,
    # Above the longest soft limit (see config.py), or a task still running would be handed to
    # another worker. Redis' own default is 1 hour.
    broker_transport_options={"visibility_timeout": settings.BROKER_VISIBILITY_TIMEOUT_SECONDS},
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
        },
        # The windows of the ZIP imports (#335): what the end of an extraction did not release.
        "release-import-queue": {
            "task": "app.tasks.release_import_queue",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": settings.EXTRACTION_QUEUE_NAME},
        },
        # The task log lines past their retention (#305), once an hour.
        "purge-task-logs": {
            "task": "app.tasks.purge_task_logs",
            "schedule": crontab(minute=15),
            "options": {"queue": settings.EXTRACTION_QUEUE_NAME},
        },
        # The tasks whose worker died while running them, once an hour.
        "reap-stuck-tasks": {
            "task": "app.tasks.reap_stuck_tasks",
            "schedule": crontab(minute=45),
            "options": {"queue": settings.EXTRACTION_QUEUE_NAME},
        },
    },
)

from app import tasks  # noqa: E402,F401
