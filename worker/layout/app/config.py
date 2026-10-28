from pydantic_settings import BaseSettings, SettingsConfigDict


class LayoutSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Shared with the extraction worker (worker/document_process/app/config.py): the queue this pod consumes.
    LAYOUT_QUEUE_NAME: str = "document_layout"

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # Where the model is in the image: read-only, nothing is downloaded when the pod runs.
    MODELS_DIR: str = "/models"
    LAYOUT_MODEL_NAME: str = "PP-DocLayoutV3_onnx"
    # Under the score or the size (pixels, on the smaller side), a region is noise and dropped; over the count,
    # the lowest scores go. Same names and defaults as the extraction worker's.
    OCR_REGION_MIN_SCORE: float = 0.5
    OCR_REGION_MIN_PIXELS: int = 32
    OCR_MAX_REGIONS_PER_PAGE: int = 200
    # A table is kept from this score, lower than the others': a table the model does not see is a table nobody
    # reads (its cells are not text regions), while a false one costs a crop. Measured on a plain drawn table the
    # model found at 0.46: to tune on real documents.
    LAYOUT_TABLE_MIN_SCORE: float = 0.3
    # Two regions of which one covers this much of the other are the same one seen twice: the better score stays.
    LAYOUT_DUPLICATE_OVERLAP: float = 0.9
    # Threads ONNX Runtime may use for one page (0: its own choice). A pod runs few pages at a time: set it to
    # the CPUs the pod is given, divided by the worker's concurrency.
    ONNX_INTRA_OP_THREADS: int = 0

    # A page's task: an exception raised in it past the limit, never a kill (#294).
    LAYOUT_TASK_SOFT_TIME_LIMIT_SECONDS: int = 5 * 60
    # Above the soft limit, or a task still running would be handed to another worker.
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 30 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = LayoutSettings()
