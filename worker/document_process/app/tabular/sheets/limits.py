import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Limits:
    """Bounds that keep one analysis' memory and output size independent of the file's size."""

    # Refused up front (before downloading) when the file is bigger.
    max_file_bytes: int = field(default_factory=lambda: _int("ANALYSIS_MAX_FILE_BYTES", 200 * 1024 * 1024))
    # xlsx/ods are zips: refuse a "zip bomb" whose XML would expand beyond this.
    max_uncompressed_bytes: int = field(default_factory=lambda: _int("ANALYSIS_MAX_UNCOMPRESSED_BYTES", 2 * 1024**3))
    max_sheets: int = field(default_factory=lambda: _int("ANALYSIS_MAX_SHEETS", 100))
    # Rows past this are ignored (the sheet is flagged truncated); statistics stay exact up to it.
    max_rows_per_sheet: int = field(default_factory=lambda: _int("ANALYSIS_MAX_ROWS_PER_SHEET", 1_000_000))
    max_columns: int = field(default_factory=lambda: _int("ANALYSIS_MAX_COLUMNS", 500))
    # Per column: distinct values tracked exactly before switching to "at least N" (bounds the Counter).
    max_distinct: int = field(default_factory=lambda: _int("ANALYSIS_MAX_DISTINCT", 1000))
    # Per numeric column: reservoir sample used for the (approximate) median and quartiles.
    reservoir_size: int = field(default_factory=lambda: _int("ANALYSIS_RESERVOIR_SIZE", 2000))
    preview_rows: int = 10
    top_values: int = 10
    sample_values: int = 5
    max_cell_chars: int = 200  # longer text is truncated before being stored/counted
