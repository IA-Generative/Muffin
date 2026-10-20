from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "document_processing"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"

    # Tesseract language code (ISO 639-2). "fra" covers French by default;
    # override per-deployment if most documents are in another language.
    OCR_LANGUAGE: str = "fra"

    # ZIP import (#223): what an archive may expand to. Over ZIP_IMPORT_MAX_FILES files or
    # ZIP_IMPORT_MAX_TOTAL_BYTES once decompressed, the whole archive is refused; a single file
    # over ZIP_IMPORT_MAX_FILE_BYTES, compressed more than ZIP_IMPORT_MAX_RATIO times, or more
    # than ZIP_IMPORT_MAX_DEPTH folders deep is skipped and listed in the summary.
    ZIP_IMPORT_MAX_FILES: int = 2000
    ZIP_IMPORT_MAX_TOTAL_BYTES: int = 2 * 1024 * 1024 * 1024
    ZIP_IMPORT_MAX_FILE_BYTES: int = 200 * 1024 * 1024
    ZIP_IMPORT_MAX_RATIO: int = 100
    ZIP_IMPORT_MAX_DEPTH: int = 20
    TESSDATA_PATH: str | None = None

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
