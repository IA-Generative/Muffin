from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    # Shared secret the document-processing (and later, agent-execution) workers
    # send back on every call to /api/internal/*. Empty means the internal API
    # is unreachable (checked at request time, not at import time).
    WORKER_API_KEY: str = ""

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
