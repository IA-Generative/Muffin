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
    # Rows of a result the model reads back, and rows kept in the evidence under the answer.
    TABULAR_PROMPT_ROWS: int = 50
    TABULAR_EVIDENCE_ROWS: int = 100

    # Only ever called when a run's own web_search_enabled is true (see AgentState) - never
    # reachable by default, matching how the chat composer's web-search toggle itself defaults
    # to off (§ security: the issue this ships for explicitly calls out never leaking private
    # document content into a web query - see research_task.py's web_search runner).
    SEARXNG_URL: str = "http://localhost:8080"
    WEB_SEARCH_RESULTS_PER_QUERY: int = 5

    # Execution budgets (§28 of the architecture brief) - checked before any
    # fan-out/targeted-research so a pathological query can't spin the
    # research DAG or the grounding loop forever.
    MAX_PARALLEL_TASKS: int = 4
    MAX_PARALLEL_SEARCHES: int = 4
    MAX_TOTAL_TASKS: int = 12
    MAX_TOTAL_SEARCHES: int = 20
    MAX_GROUNDING_RESEARCHES: int = 1
    # How many times in a row the assistant may ask questions before it carries on with assumptions
    # instead (#344) - the model must not question the user in a loop.
    MAX_QUESTION_ROUNDS: int = 2
    SEARCH_RESULTS_PER_QUERY: int = 5
    # How many collections VDB routing may select per routing call once sub-collections exist
    # (#233) - each is one index query. Picks over this cap are reported back as unexplored so
    # the user can ask to go further.
    MAX_ROUTED_COLLECTIONS: int = 15
    # Routing confidence: before searching, one probe over the chunks of the accessible collections
    # (the best ROUTING_PROBE_RESULTS hits) says which collections the question lands in. A collection
    # holding at least ROUTING_CLEAR_SHARE of the hits is the obvious one; one holding at least
    # ROUTING_LEAN_SHARE and ROUTING_LEAN_RATIO times the next is a likely one; otherwise nothing
    # dominates and the user is asked. ROUTING_PROBE_MAX_COLLECTIONS bounds the probe for a user with
    # many collections (the description pre-filter keeps the closest).
    ROUTING_PROBE_RESULTS: int = 30
    ROUTING_PROBE_MAX_COLLECTIONS: int = 40
    ROUTING_CLEAR_SHARE: float = 0.6
    ROUTING_LEAN_SHARE: float = 0.4
    ROUTING_LEAN_RATIO: float = 1.5
    ROUTING_MAX_OPTIONS: int = 4

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
