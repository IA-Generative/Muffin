from pydantic_settings import BaseSettings, SettingsConfigDict


class TabularSettings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    # The queue this pod consumes, and the one the agent sends to (worker/agent_execution/app/config.py). Not
    # `tabular_query`: that is the name of the agent's own task.
    SQL_QUEUE_NAME: str = "tabular_sql"

    # A read-only key: this pod only ever reads the typed copies of the sheets (a bucket policy is the real guard, the
    # code below also refuses any key that is not one of them).
    AWS_ENDPOINT_URL: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "rustfsadmin"
    AWS_SECRET_ACCESS_KEY: str = "rustfsadmin"
    AWS_BUCKET: str = "muffin-documents"
    STORAGE_CONNECT_TIMEOUT_SECONDS: int = 10
    STORAGE_READ_TIMEOUT_SECONDS: int = 60

    # Per query, whatever the SQL asks for.
    # Rows given back (the query itself may read millions): the agent gets a summary, not a dump.
    QUERY_MAX_ROWS: int = 200
    # One cell is cut here, and the whole result is cut when its text gets this big.
    QUERY_MAX_CELL_CHARS: int = 500
    QUERY_MAX_RESULT_CHARS: int = 200_000
    QUERY_TIMEOUT_SECONDS: float = 30
    # DuckDB spills to disk beyond this, and fails the query rather than the process if it still does not fit.
    QUERY_MEMORY_LIMIT: str = "512MB"
    QUERY_THREADS: int = 2
    # Parquet downloaded for one query, and how many files (schemas) it may join.
    QUERY_MAX_TABLE_BYTES: int = 500 * 1024 * 1024
    QUERY_MAX_FILES: int = 10
    QUERY_MAX_SHEETS: int = 100
    # Where a query's private folder is made (the pod's writable volume).
    QUERY_WORK_DIR: str | None = None

    # Above the query's own timeout (the download comes on top of it): an exception raised in the task, never a kill.
    SQL_TASK_SOFT_TIME_LIMIT_SECONDS: int = 3 * 60
    BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 30 * 60

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")


settings = TabularSettings()
