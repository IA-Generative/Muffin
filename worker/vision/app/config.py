from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # Shared with the extraction worker (worker/document_process/app/config.py): the queue this pod consumes.
    VISION_QUEUE_NAME: str = "document_vision"

    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # Where the model is in the image: read-only, nothing is downloaded when the pod runs.
    MODELS_DIR: str = "/models"
    VISION_MODEL_NAME: str = "Florence-2-base"
    # What the model is asked: its "detailed caption" task, the longest of its three.
    VISION_TASK: str = "<MORE_DETAILED_CAPTION>"
    # A caption is a sentence or two: this bounds the generation, and so the time of one image.
    VISION_MAX_NEW_TOKENS: int = 128
    VISION_NUM_BEAMS: int = 3
    # A little of the page around the region, or the edge of an image that the layout cut close is lost.
    VISION_CROP_MARGIN_PIXELS: int = 8
    # The regions of a page, at most - the extraction worker caps them lower; this is the pod's own guard.
    VISION_MAX_REGIONS: int = 50
    # Threads PyTorch may use for one inference (0: its own choice). A pod runs few images at a time: set it to the
    # CPUs the pod is given, divided by the worker's concurrency.
    TORCH_THREADS: int = 0

    # The hub's models that read images (any `model` of the task other than VISION_MODEL_NAME) are asked through the
    # backend's LLM proxy: the pod holds no key of the hub, and the backend records what is consumed.
    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""
    HUB_TIMEOUT_SECONDS: int = 120
    HUB_MAX_TOKENS: int = 300

    # A page's task: an exception raised in it past the limit, never a kill (#294).
    VISION_TASK_SOFT_TIME_LIMIT_SECONDS: int = 5 * 60
    # Above the soft limit, or a task still running would be handed to another worker.
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 30 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = VisionSettings()
