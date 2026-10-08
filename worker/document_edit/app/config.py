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

    # Model used to plan the edit. Empty means the LLM hub's default chat model.
    EDIT_LLM_MODEL: str = ""
    # Room for the operations list the model writes back - far less than a whole rewritten document.
    EDIT_MAX_TOKENS: int = 4096
    # How many times the model may be asked again with the reason its previous answer was refused
    # (invalid JSON, an operation aimed at something that doesn't exist...).
    EDIT_MAX_ATTEMPTS: int = 3
    # Largest document outline (characters) sent to the model; beyond it the job fails with a clear
    # message rather than editing blind.
    EDIT_MAX_OUTLINE_CHARS: int = 60000

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
