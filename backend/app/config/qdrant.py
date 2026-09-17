from pydantic_settings import BaseSettings, SettingsConfigDict


class QdrantSettings(BaseSettings):
    QDRANT_URL: str = "http://localhost:6333"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
