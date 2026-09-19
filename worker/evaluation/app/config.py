from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "evaluation"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    # How many chunks to retrieve per question when no `k` is explicitly passed to the task -
    # mirrors EvaluationTriggerRequest.k's own default on the backend (app/schemas/evaluation.py).
    DEFAULT_TOP_K: int = 5

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
