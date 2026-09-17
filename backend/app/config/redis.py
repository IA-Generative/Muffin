from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
