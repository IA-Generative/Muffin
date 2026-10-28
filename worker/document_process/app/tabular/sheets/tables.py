"""Typed copies of the sheets, for SQL: one Parquet file per sheet, written in a second streaming pass.

The first pass (analyzer.py) decides the header and the type of every column; this pass re-reads the file and writes
the rows with those types. Memory stays flat: rows go to Parquet in batches. A column keeps its native type only if
every cell that has a value is of that type (error cells like #N/A become NULL); otherwise it is stored as text, so
no value is ever lost to a conversion."""

import datetime as dt
import itertools
import posixpath
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.tabular.sheets.limits import Limits
from app.tabular.sheets.profile import value_kind
from app.tabular.sheets.readers import open_sheets

BATCH_ROWS = 20_000

# Arrow type, and the name DuckDB gives it (what the agent writes in a CAST and sees in the column list).
_TYPES = {
    "integer": (pa.int64(), "BIGINT"),
    "number": (pa.float64(), "DOUBLE"),
    "boolean": (pa.bool_(), "BOOLEAN"),
    "date": (pa.date32(), "DATE"),
    "datetime": (pa.timestamp("us"), "TIMESTAMP"),
    "time": (pa.time64("us"), "TIME"),
    "text": (pa.string(), "VARCHAR"),
}


def table_key(result_key: str, sheet_index: int) -> str:
    """Where a sheet's Parquet lives: next to its analyse.json, so it follows the file's version (and goes with
    the file when it is deleted). Worker side only: the backend never needs this key."""
    return posixpath.join(posixpath.dirname(result_key), "tables", f"{sheet_index}.parquet")


def column_kind(column: dict) -> str:
    """The storage kind of an analysed column: a native kind when all its values share it, else 'text'."""
    kinds = {kind for kind, count in column["type_counts"].items() if kind != "error" and count}
    if not kinds:
        return "text"
    if kinds <= {"integer"}:
        return "integer"
    if kinds <= {"integer", "number"}:
        return "number"
    if kinds <= {"date", "datetime"}:
        return "datetime" if "datetime" in kinds else "date"
    if len(kinds) == 1 and next(iter(kinds)) in _TYPES:
        return next(iter(kinds))
    return "text"


def sql_type(column: dict) -> str:
    """The SQL type a column is stored with (the name DuckDB gives it): what the agent writes in a CAST."""
    return _TYPES[column_kind(column)][1]


def _as_time(value) -> dt.time | None:
    if isinstance(value, dt.timedelta):  # xls/ods durations
        seconds = int(value.total_seconds()) % 86400
        return dt.time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return value


def _convert(value, kind: str, limits: Limits):
    """One cell as the column's storage kind, or None when it has no value (or an error value)."""
    if value is None or value == "":
        return None
    if kind == "text":
        text = value.isoformat() if hasattr(value, "isoformat") else str(value)
        return text if len(text) <= limits.max_cell_chars * 10 else text[: limits.max_cell_chars * 10]
    if value_kind(value) == "error":
        return None
    if kind == "number":
        return float(value)
    if kind == "datetime" and type(value) is dt.date:
        return dt.datetime.combine(value, dt.time())
    if kind == "time":
        return _as_time(value)
    return value


def _batches(rows: Iterator[tuple], kinds: list[str], names: list[str], schema: pa.Schema, limits: Limits):
    width = len(kinds)
    columns: list[list] = [[] for _ in range(width)]
    count = 0
    for row in rows:
        for index in range(width):
            cell = row[index] if index < len(row) else None
            try:
                columns[index].append(_convert(cell, kinds[index], limits))
            except (ValueError, TypeError, OverflowError):
                columns[index].append(None)
        count += 1
        if count == BATCH_ROWS:
            yield pa.record_batch(columns, schema=schema)
            columns, count = [[] for _ in range(width)], 0
    if count:
        yield pa.record_batch(columns, schema=schema)


def write_tables(path: Path, file_name: str, result: dict, destination: Path, limits: Limits | None = None) -> dict:
    """Writes `destination/<sheet index>.parquet` for every sheet of `result` that has rows and columns, and
    returns {sheet index: {"rows", "columns": [{"name", "sql_type"}]}} for analyse.json.

    `result` is what analyze_file returned for this same file: it holds the header decision, the column names and
    types, and the number of rows to keep (so that truncated sheets stay truncated in the same place)."""
    limits = limits or Limits()
    wanted = {sheet["index"]: sheet for sheet in result["sheets"] if sheet["rows"] and sheet["columns"]}
    described: dict[int, dict] = {}
    for position, stream in enumerate(open_sheets(path, file_name, limits)):
        if not wanted or position > max(wanted):
            break
        sheet = wanted.get(position)
        if sheet is None:
            continue
        rows = iter(stream.rows)
        if sheet["header_detected"] and stream.header is None:
            next(rows, None)  # the header is not data (a reader that declares its header does not repeat it)
        kinds = [column_kind(column) for column in sheet["columns"]]
        names = [column["name"] for column in sheet["columns"]]
        schema = pa.schema([pa.field(name, _TYPES[kind][0]) for name, kind in zip(names, kinds, strict=True)])
        written = 0
        with pq.ParquetWriter(destination / f"{position}.parquet", schema, compression="zstd") as writer:
            for batch in _batches(itertools.islice(rows, sheet["rows"]), kinds, names, schema, limits):
                writer.write_batch(batch)
                written += batch.num_rows
        described[position] = {
            "rows": written,
            "columns": [{"name": name, "sql_type": _TYPES[kind][1]} for name, kind in zip(names, kinds, strict=True)],
        }
    return described
