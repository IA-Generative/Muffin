from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_QUEUE_NAME: str = "agent_execution"

    BACKEND_API_URL: str = "http://localhost:8000"
    WORKER_API_KEY: str = ""

    # The tabular_query tool runs no SQL itself and reads no file: it sends its queries to the SQL worker
    # (worker/tabular, #432), on this queue, and waits for the answer (#433).
    SQL_QUEUE_NAME: str = "tabular_sql"
    # Queries one task may run before it is asked to conclude, the time it waits for one answer (the worker's own
    # limit is far below), and how often it looks whether the answer is there.
    TABULAR_MAX_STEPS: int = 8
    TABULAR_QUERY_TIMEOUT_SECONDS: float = 120
    TABULAR_POLL_SECONDS: float = 0.3
    # The files one task may query: the SQL worker's own limit (QUERY_MAX_FILES).
    TABULAR_MAX_FILES: int = 10
    # Charts one answer may carry (#434) - the backend refuses more - and the wait for one to be drawn.
    TABULAR_MAX_CHARTS: int = 6
    # Categories a chart stays readable up to (the SQL worker's CHART_MAX_CATEGORIES): what the model is told.
    TABULAR_MAX_CATEGORIES_HINT: int = 40
    TABULAR_CHART_TIMEOUT_SECONDS: float = 90
    # Rows of a result the model reads back, and rows kept in the evidence under the answer.
    TABULAR_PROMPT_ROWS: int = 50
    TABULAR_EVIDENCE_ROWS: int = 100

    # Only ever called when a run's own web_search_enabled is true (see AgentState) - never
    # reachable by default, matching how the chat composer's web-search toggle itself defaults
    # to off (§ security: the issue this ships for explicitly calls out never leaking private
    # document content into a web query - see research_task.py's web_search runner).
    SEARXNG_URL: str = "http://localhost:8080"
    WEB_SEARCH_RESULTS_PER_QUERY: int = 5

    # Execution budgets (§28 of the architecture brief) - checked before the research fans out, so a pathological query
    # can't start more tasks than this.
    MAX_PARALLEL_TASKS: int = 4
    MAX_TOTAL_TASKS: int = 12
    # The gate (no model): the passages of a content search that make an answer worth writing, and the score under
    # which a passage does not count (0: any does - to be calibrated on real questions).
    GATE_MIN_EVIDENCE: int = 1
    GATE_MIN_SCORE: float = 0.0
    # How many times in a row the assistant may ask questions before it carries on with assumptions
    # instead (#344) - the model must not question the user in a loop.
    MAX_QUESTION_ROUNDS: int = 2
    SEARCH_RESULTS_PER_QUERY: int = 5

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
