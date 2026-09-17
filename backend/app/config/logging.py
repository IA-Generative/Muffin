from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
