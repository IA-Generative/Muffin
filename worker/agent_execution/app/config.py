from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "agent_execution"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    # RustFS/S3 credentials for DuckDB httpfs - the tabular_query tool reads tabular files
    # directly from object storage (same pattern as worker/document_process), never downloads
    # them to disk first.
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"

    # Only ever called when a run's own web_search_enabled is true (see AgentState) - never
    # reachable by default, matching how the chat composer's web-search toggle itself defaults
    # to off (§ security: the issue this ships for explicitly calls out never leaking private
    # document content into a web query - see research_task.py's web_search runner).
    SEARXNG_URL: str = "http://localhost:8080"
    WEB_SEARCH_RESULTS_PER_QUERY: int = 5

    # Execution budgets (§28 of the architecture brief) - checked before any
    # fan-out/replan/targeted-research so a pathological query can't spin the
    # research DAG or the grounding loop forever.
    MAX_PARALLEL_TASKS: int = 4
    MAX_PARALLEL_SEARCHES: int = 4
    MAX_TOTAL_TASKS: int = 12
    MAX_TOTAL_SEARCHES: int = 20
    MAX_REPLANS: int = 2
    MAX_GROUNDING_RESEARCHES: int = 1
    SEARCH_RESULTS_PER_QUERY: int = 5

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
