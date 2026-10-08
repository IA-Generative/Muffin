from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Dedicated queue, separate from document_processing/agent_execution/evaluation: an edit job
    # runs an LLM and a LibreOffice conversion, neither of which should ever delay an ingestion or
    # a chat answer. Must match backend/app/core/tasks.py's DOCUMENT_EDIT_QUEUE.
    CELERY_QUEUE_NAME: str = "document_edit"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
