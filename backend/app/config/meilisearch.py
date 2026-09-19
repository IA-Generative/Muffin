from pydantic_settings import BaseSettings, SettingsConfigDict


class MeilisearchSettings(BaseSettings):
    MEILI_URL: str = "http://localhost:7700"
    # None (no key) works against a dev instance started without MEILI_MASTER_KEY - a real
    # deployment always sets one, Meilisearch itself refuses to start in production without it.
    MEILI_API_KEY: str | None = None

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
