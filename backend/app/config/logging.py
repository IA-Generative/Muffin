from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"
    # How long the lines workers log for their tasks are kept (#305) - as long as Celery keeps a task's
    # result (result_expires in the workers' celery_app.py).
    TASK_LOG_RETENTION_DAYS: int = 7

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
