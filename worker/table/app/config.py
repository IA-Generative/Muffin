from pydantic_settings import BaseSettings, SettingsConfigDict


class TableSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Shared with the extraction worker (worker/document_process/app/config.py): the queue this pod consumes.
    TABLE_QUEUE_NAME: str = "document_table"

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # Where the models are in the image: read-only, nothing is downloaded when the pod runs.
    MODELS_DIR: str = "/models"
    # SLANet_plus reads a table's structure; PP-OCRv5 mobile (the detector and the Latin recognizer, as in the ocr pod)
    # reads the text of its cells.
    TABLE_MODEL_NAME: str = "SLANet_plus_onnx"
    OCR_DET_MODEL_NAME: str = "PP-OCRv5_mobile_det_onnx"
    OCR_REC_MODEL_NAME: str = "latin_PP-OCRv5_mobile_rec_onnx"
    # A little of the page around the table, or a border that the layout cut close is lost.
    TABLE_CROP_MARGIN_PIXELS: int = 8
    # A table over this many cells is refused: a spreadsheet is not read off a scan, and the page falls back.
    TABLE_MAX_CELLS: int = 5000
    # The tables of a page, at most - the layout pod's own cap is far above what a page holds.
    TABLE_MAX_PER_PAGE: int = 20
    # Threads ONNX Runtime may use for one table (0: its own choice). A pod runs few pages at a time: set it to the CPUs
    # the pod is given, divided by the worker's concurrency.
    ONNX_INTRA_OP_THREADS: int = 0

    # A page's task: an exception raised in it past the limit, never a kill (#294).
    TABLE_TASK_SOFT_TIME_LIMIT_SECONDS: int = 5 * 60
    # Above the soft limit, or a task still running would be handed to another worker.
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 30 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = TableSettings()
