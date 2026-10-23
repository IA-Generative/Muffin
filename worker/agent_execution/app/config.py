from typing import Literal

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
    # How many times in a row the assistant may ask questions before it carries on with assumptions
    # instead (#344) - the model must not question the user in a loop.
    MAX_QUESTION_ROUNDS: int = 2
    SEARCH_RESULTS_PER_QUERY: int = 5
    # How many collections VDB routing may select per routing call once sub-collections exist
    # (#233) - each is one index query. Picks over this cap are reported back as unexplored so
    # the user can ask to go further.
    MAX_ROUTED_COLLECTIONS: int = 15

    # Delegating an edit of a living document to the editing agent (#171): how long the run waits
    # for it, and how often it asks the backend where it stands. The editing agent itself is
    # bounded (its own task time limit), this just stops a run from waiting on it forever.
    # The Markdown document the agent writes when asked to create one: its length in tokens, and the
    # most characters kept (a longer one is cut at its last whole paragraph).
    CREATE_MAX_TOKENS: int = 4000
    CREATE_MAX_CHARS: int = 30000
    EDIT_WAIT_SECONDS: int = 300
    EDIT_POLL_SECONDS: float = 2.0

    # Logging (#305): stdout - JSON for kubectl/Loki, or readable - from LOG_LEVEL up. The lines a task
    # logs from TASK_LOG_LEVEL up are also sent to the backend, to be followed in Muffin as it runs.
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_LEVEL: str = "INFO"
    TASK_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = WorkerSettings()
