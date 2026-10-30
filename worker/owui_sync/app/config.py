from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Dedicated queue, separate from document_processing/agent_execution/document_edit: a synchronisation
    # lists and copies a whole Open WebUI, which should never delay an ingestion or a chat answer. Must match
    # backend/app/core/tasks.py's OWUI_SYNC_QUEUE.
    CELERY_QUEUE_NAME: str = "owui_sync"

    # Where the summary of a copied file is made (#457): the enrichment queue of worker/document_process, and the
    # lowest Celery priority, so that it holds up neither the ingestion of Muffin's documents nor an answer. Must
    # match backend/app/core/tasks.py's DOCUMENT_ENRICHMENT_QUEUE and BULK_PRIORITY.
    ENRICHMENT_QUEUE_NAME: str = "document_enrichment"
    SUMMARY_PRIORITY: int = 9

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    # The Open WebUI read by the synchronisation (#453): its REST API, with the key of an administrator.
    OWUI_BASE_URL: str = "http://localhost:3001"
    OWUI_API_KEY: str = ""
    # A synchronisation every this many minutes, started by the beat (`celery -A app.celery_app beat`, one
    # process, not one per worker pod). 0 starts none by itself: only the administrator's button does.
    OWUI_SYNC_INTERVAL_MINUTES: int = 60

    # S3 and Qdrant are the ones Open WebUI already uses: the worker reads the files and the vectors where
    # they are and copies neither.
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    # Muffin's bucket, the one of the other workers (AWS_BUCKET). When Open WebUI keeps its files in that same bucket,
    # a file is copied under the very key it has there; a file in another bucket keeps `s3://<bucket>/<key>`.
    AWS_BUCKET: str = "muffin-documents"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    # Prefix of Open WebUI's Qdrant collections (QDRANT_COLLECTION_PREFIX on its side).
    OWUI_QDRANT_PREFIX: str = "open-webui"

    # Logging (#305): stdout - JSON for kubectl/Loki, or readable - from LOG_LEVEL up. The lines a task
    # logs from TASK_LOG_LEVEL up are also sent to the backend, to be followed in Muffin as it runs.
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"
    TASK_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
