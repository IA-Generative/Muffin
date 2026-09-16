from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://muffin:muffin@localhost:5432/muffin"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
