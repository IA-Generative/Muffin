from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "document_processing"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    RUSTFS_ENDPOINT_URL: str = "http://localhost:9000"
    RUSTFS_ACCESS_KEY: str = "rustfsadmin"
    RUSTFS_SECRET_KEY: str = "rustfsadmin"
    RUSTFS_BUCKET: str = "muffin-documents"

    # Tesseract language code (ISO 639-2). "fra" covers French by default;
    # override per-deployment if most documents are in another language.
    OCR_LANGUAGE: str = "fra"
    TESSDATA_PATH: str | None = None

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
