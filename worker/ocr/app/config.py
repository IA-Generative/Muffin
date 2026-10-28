from pydantic_settings import BaseSettings, SettingsConfigDict


class OcrSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Shared with the extraction worker (worker/document_process/app/config.py): the queue this pod consumes.
    OCR_QUEUE_NAME: str = "document_ocr"

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # Where the models are in the image: read-only, nothing is downloaded when the pod runs.
    MODELS_DIR: str = "/models"
    # PP-OCRv5 mobile: the text detector, and the recognizer of the Latin scripts (French accents, ligatures, the
    # euro sign and the typographic dashes and apostrophes included).
    OCR_DET_MODEL_NAME: str = "PP-OCRv5_mobile_det_onnx"
    OCR_REC_MODEL_NAME: str = "latin_PP-OCRv5_mobile_rec_onnx"
    # A region is read from a crop a few pixels wider than it, or the edge of a glyph is cut off.
    OCR_REGION_PADDING_PIXELS: int = 8
    # White around a crop: a very flat crop (a title, a single line) is otherwise cut into pieces by the detector
    # - "Rapport annuel d'activité" came out as three lines without it, and as one from 16 pixels.
    OCR_CROP_BORDER_PIXELS: int = 32
    # A line under this score is dropped. 0 keeps every line, each with its score: it is for the caller to decide
    # what a poor reading is worth.
    OCR_LINE_MIN_SCORE: float = 0.0
    # Threads ONNX Runtime may use for one region (0: its own choice). A pod runs few pages at a time: set it to
    # the CPUs the pod is given, divided by the worker's concurrency.
    ONNX_INTRA_OP_THREADS: int = 0

    # A page's task: an exception raised in it past the limit, never a kill (#294).
    OCR_TASK_SOFT_TIME_LIMIT_SECONDS: int = 5 * 60
    # Above the soft limit, or a task still running would be handed to another worker.
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 30 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = OcrSettings()
