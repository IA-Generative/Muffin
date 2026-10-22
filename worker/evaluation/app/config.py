from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "evaluation"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    # How many chunks to retrieve per question when no `k` is explicitly passed to the task -
    # mirrors EvaluationTriggerRequest.k's own default on the backend (app/schemas/evaluation.py).
    DEFAULT_TOP_K: int = 5

    # promptfoo drives the evaluation: how many tests it may run in parallel, and how
    # long the whole subprocess may take before the task gives up on it.
    EVAL_CONCURRENCY: int = 4
    EVAL_TIMEOUT_SECONDS: int = 3600

    # Logging (#305): stdout - JSON for kubectl/Loki, or readable - from LOG_LEVEL up. The lines a task
    # logs from TASK_LOG_LEVEL up are also sent to the backend, to be followed in Muffin as it runs.
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"
    TASK_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
