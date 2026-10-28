from dataclasses import dataclass, field

from app.config import settings


@dataclass(frozen=True)
class QueryLimits:
    """Bounds on one SQL query, whatever the SQL asks for (see the QUERY_* settings)."""

    max_rows: int = field(default_factory=lambda: settings.QUERY_MAX_ROWS)
    max_cell_chars: int = field(default_factory=lambda: settings.QUERY_MAX_CELL_CHARS)
    max_result_chars: int = field(default_factory=lambda: settings.QUERY_MAX_RESULT_CHARS)
    timeout_seconds: float = field(default_factory=lambda: settings.QUERY_TIMEOUT_SECONDS)
    memory_limit: str = field(default_factory=lambda: settings.QUERY_MEMORY_LIMIT)
    threads: int = field(default_factory=lambda: settings.QUERY_THREADS)
    max_table_bytes: int = field(default_factory=lambda: settings.QUERY_MAX_TABLE_BYTES)
    max_files: int = field(default_factory=lambda: settings.QUERY_MAX_FILES)
    max_sheets: int = field(default_factory=lambda: settings.QUERY_MAX_SHEETS)
