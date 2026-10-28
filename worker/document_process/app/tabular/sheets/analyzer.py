import datetime as dt
import hashlib
import itertools
from collections.abc import Iterator
from pathlib import Path

from app.tabular.sheets.limits import Limits
from app.tabular.sheets.profile import ColumnProfile, _jsonable
from app.tabular.sheets.readers import SheetStream, detect_format, open_sheets

SCHEMA_VERSION = 1


def analyze_file(path: Path, file_name: str, limits: Limits | None = None) -> dict:
    """Profiles a spreadsheet (csv, xlsx, xls, ods) in one streaming pass per sheet.

    Memory stays flat whatever the file's size: rows are consumed one at a time and only bounded
    per-column state is kept. Raises UnsupportedFormat / UnreadableFile for files it cannot read."""
    limits = limits or Limits()
    size = path.stat().st_size
    result: dict = {
        "schema_version": SCHEMA_VERSION,
        "file": {"name": file_name, "format": detect_format(path, file_name), "size_bytes": size},
        "analyzed_at": dt.datetime.now(dt.UTC).isoformat(),
        "sheets": [],
        "warnings": [],
    }
    for position, sheet in enumerate(open_sheets(path, file_name, limits)):
        if position >= limits.max_sheets:
            result["warnings"].append(f"Only the first {limits.max_sheets} sheets were analyzed")
            break
        result["sheets"].append(_analyze_sheet(position, sheet, limits))
    result["summary"] = {
        "sheets": len(result["sheets"]),
        "rows": sum(sheet["rows"] for sheet in result["sheets"]),
        "truncated": any(sheet["truncated"] for sheet in result["sheets"]),
    }
    if not result["sheets"] or all(sheet["rows"] == 0 for sheet in result["sheets"]):
        result["warnings"].append("The file contains no data")
    return result


def _looks_like_header(first: tuple, second: tuple | None) -> bool:
    """The first row is a header when it is made of text labels filling at least half the width, and either
    the next row holds something that is not text (numbers, dates...) or the labels are all distinct."""
    cells = [cell for cell in first if cell is not None and cell != ""]
    if not cells or len(cells) * 2 < len(first):
        return False
    if not all(isinstance(cell, str) and len(cell) <= 100 for cell in cells):
        return False
    if second is not None and any(cell is not None and not isinstance(cell, str) for cell in second):
        return True
    labels = [cell.strip() for cell in cells]
    return len(set(labels)) == len(labels)


def _column_names(header: tuple | None, width: int) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for index in range(width):
        raw = header[index] if header and index < len(header) else None
        name = str(raw).strip() if raw not in (None, "") else f"col_{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return names


def _analyze_sheet(position: int, sheet: SheetStream, limits: Limits) -> dict:
    warnings: list[str] = []
    rows: Iterator[tuple] = iter(sheet.rows)
    if sheet.header is not None:
        # The reader knows the column names (Parquet, JSON): nothing to guess, and `rows` is data only.
        first, second = tuple(sheet.header), None
        header = first
    else:
        first = next(rows, None)
        second = next(rows, None) if first is not None else None
        header = first if first is not None and _looks_like_header(first, second) else None

    columns: dict[int, ColumnProfile] = {}
    preview: list[list] = []
    data_rows = 0
    truncated = False
    width_capped = False
    max_width = 0

    def feed(row: tuple) -> None:
        nonlocal data_rows, width_capped, max_width
        data_rows += 1
        width = len(row)
        if width > limits.max_columns:
            width_capped = True
            row = row[: limits.max_columns]
            width = limits.max_columns
        max_width = max(max_width, width)
        if len(preview) < limits.preview_rows:
            preview.append([_jsonable(cell) if cell is not None else None for cell in row])
        for index, cell in enumerate(row):
            profile = columns.get(index)
            if profile is None:
                profile = columns[index] = ColumnProfile(limits, index, seed=index)
            profile.add(cell)

    if first is not None:
        if header is None:
            feed(first)
        else:
            max_width = min(len(first), limits.max_columns)
        # `second` was read ahead to decide about the header; it is the first row left to profile.
        remaining = rows if second is None else itertools.chain([second], rows)
        for row in remaining:
            if data_rows >= limits.max_rows_per_sheet:
                truncated = True
                break
            feed(row)

    if truncated:
        warnings.append(f"Only the first {limits.max_rows_per_sheet} rows were analyzed")
    if width_capped:
        warnings.append(f"Only the first {limits.max_columns} columns were analyzed")
    names = _column_names(header, max_width)
    summaries = []
    for index in range(max_width):
        profile = columns.get(index) or ColumnProfile(limits, index)
        summaries.append(profile.summary(names[index], data_rows))
    return {
        "index": position,
        "name": sheet.name,
        "hidden": sheet.hidden,
        "rows": data_rows,
        "header_detected": header is not None,
        "truncated": truncated,
        "columns": summaries,
        "preview": preview,
        "warnings": warnings,
    }


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
