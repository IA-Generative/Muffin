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


@dataclass(frozen=True)
class ChartLimits:
    """Bounds on one chart: what it may plot, and how big the image is (fixed, whatever the data)."""

    # Rows of the query that are drawn (the query runs again, with room for more points than the agent sees).
    max_points: int = field(default_factory=lambda: settings.CHART_MAX_POINTS)
    # Bars and slices stay readable only up to here: the author is asked to aggregate or keep the largest.
    max_categories: int = field(default_factory=lambda: settings.CHART_MAX_CATEGORIES)
    max_series: int = 12
    # A pie keeps its largest slices and groups the rest.
    max_slices: int = 11
    # 900 x 540 px. A small figure at a high resolution: text is relatively larger, so it stays readable when the
    # image is shown at the width of a message.
    width_inches: float = 7.2
    height_inches: float = 4.32
    dpi: int = 125
