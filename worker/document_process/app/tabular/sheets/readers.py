"""Streaming readers: every format yields (sheet name, iterator of row tuples) and never holds a whole sheet.

Rows that are entirely empty are skipped. Readers know nothing about statistics: they only turn a file into
Python values (str, int, float, bool, date, datetime, time, None).

Adapted from spreadsheet-analyser (Apache-2.0, analysis-worker/app/analysis/readers.py). Added here: the formats
Muffin already took - TSV and PSV (a CSV with its delimiter given), JSON, JSONL and Parquet (read by DuckDB, which
knows their types and their column names: such a sheet declares its own header)."""

import csv
import datetime as dt
import decimal
import json
import re
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from app.tabular.sheets.limits import Limits

Row = tuple


class UnsupportedFormat(ValueError):
    pass


class UnreadableFile(ValueError):
    """The file is corrupt, empty, encrypted, or exceeds a safety limit."""


@dataclass
class SheetStream:
    name: str
    rows: Iterator[Row]
    hidden: bool = False
    # Set by a reader that knows its column names (Parquet, JSON): `rows` then holds data only. Left None, the
    # first row of `rows` may be a header, which the analysis decides.
    header: tuple | None = None


_DELIMITED = {"csv": None, "tsv": "\t", "psv": "|"}
_DUCKDB_FORMATS = ("json", "jsonl", "parquet")
FORMATS = ("csv", "tsv", "psv", "json", "jsonl", "parquet", "xlsx", "xls", "ods")


def detect_format(path: Path, file_name: str) -> str:
    extension = Path(file_name).suffix.lower().lstrip(".")
    extension = {"xlsm": "xlsx", "ndjson": "jsonl"}.get(extension, extension)
    if extension not in FORMATS:
        raise UnsupportedFormat(f"Unsupported file type '.{extension}' (expected {', '.join(FORMATS)})")
    with path.open("rb") as handle:
        magic = handle.read(8)
    if extension in ("xlsx", "ods") and not magic.startswith(b"PK"):
        raise UnreadableFile(f"'{file_name}' is not a valid .{extension} file (not a zip archive)")
    if extension == "xls" and not magic.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnreadableFile(f"'{file_name}' is not a valid .xls file")
    if extension == "parquet" and not magic.startswith(b"PAR1"):
        raise UnreadableFile(f"'{file_name}' is not a valid .parquet file")
    return extension


def open_sheets(path: Path, file_name: str, limits: Limits) -> Iterator[SheetStream]:
    fmt = detect_format(path, file_name)
    if fmt in ("xlsx", "ods"):
        _check_zip(path, limits)
    if fmt in _DELIMITED:
        # A CSV has no sheets: it is named after the uploaded file (`path` may be an anonymous temporary copy).
        return _read_csv(path, limits, sheet_name=Path(file_name).stem, delimiter=_DELIMITED[fmt])
    if fmt in _DUCKDB_FORMATS:
        return _read_duckdb(path, fmt, sheet_name=Path(file_name).stem)
    return {"xlsx": _read_xlsx, "ods": _read_ods, "xls": _read_xls}[fmt](path, limits)


def _check_zip(path: Path, limits: Limits) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as error:
        raise UnreadableFile(f"Corrupt archive: {error}") from error
    if total > limits.max_uncompressed_bytes:
        raise UnreadableFile(
            f"Archive expands to {total // 2**20} MB, over the {limits.max_uncompressed_bytes // 2**20} MB limit"
        )


# --- CSV ---


def _read_csv(path: Path, limits: Limits, sheet_name: str, delimiter: str | None = None) -> Iterator[SheetStream]:
    with path.open("rb") as handle:
        sample = handle.read(1 << 20)
    try:
        sample.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError as error:
        # A multi-byte character cut by the 1 MB sample boundary is not a real decoding problem.
        encoding = "utf-8-sig" if error.start >= len(sample) - 4 and len(sample) == 1 << 20 else "cp1252"
    text_sample = sample[: 1 << 16].decode(encoding, errors="replace")
    if delimiter is not None:
        # The file says what it is (.tsv, .psv): no need to guess.
        class dialect(csv.excel):  # noqa: N801 - a dialect is a class, named as the module's other
            pass

        dialect.delimiter = delimiter
    else:
        try:
            dialect = csv.Sniffer().sniff(text_sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
    csv.field_size_limit(10 * 1024 * 1024)

    def rows() -> Iterator[Row]:
        with path.open(newline="", encoding=encoding, errors="replace") as handle:
            for record in csv.reader(handle, dialect):
                if any(cell.strip() for cell in record):
                    yield tuple(_parse_csv_cell(cell, dialect.delimiter) for cell in record)

    yield SheetStream(name=sheet_name, rows=rows())


# --- JSON, JSONL, Parquet (DuckDB reads the file: it knows the columns and their types) ---

_DUCKDB_BATCH = 10_000


def _plain(value):
    """A DuckDB value as one the analysis knows: nested values become their JSON text, decimals floats."""
    if value is None or isinstance(value, bool | int | float | str | dt.datetime | dt.date | dt.time | dt.timedelta):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return bytes(value).hex()
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _read_duckdb(path: Path, fmt: str, sheet_name: str) -> Iterator[SheetStream]:
    import duckdb

    quoted = str(path).replace("'", "''")
    source = {
        "parquet": f"read_parquet('{quoted}')",
        "jsonl": f"read_json_auto('{quoted}', format='newline_delimited')",
        "json": f"read_json_auto('{quoted}')",
    }[fmt]
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET threads=2")
        connection.execute("SET memory_limit='2GB'")
        result = connection.execute(f"SELECT * FROM {source}")
    except duckdb.Error as error:
        connection.close()
        raise UnreadableFile(f"Cannot read the {fmt} file: {str(error).splitlines()[0]}") from error
    header = tuple(description[0] for description in result.description)

    def rows() -> Iterator[Row]:
        try:
            while batch := result.fetchmany(_DUCKDB_BATCH):
                for record in batch:
                    row = tuple(_plain(value) for value in record)
                    if any(cell is not None and cell != "" for cell in row):
                        yield row
        finally:
            connection.close()

    yield SheetStream(name=sheet_name, rows=rows(), header=header)


_INT = re.compile(r"[+-]?(0|[1-9]\d*)")
_FLOAT = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")
_FLOAT_COMMA = re.compile(r"[+-]?\d+,\d+")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?")
_FR_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _parse_csv_cell(raw: str, delimiter: str):
    """CSV is untyped text: recover numbers/dates/booleans conservatively (IDs like '007' stay text)."""
    value = raw.strip()
    if not value:
        return None
    if _INT.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value) and not (value.isdigit() or value.lstrip("+-").isdigit()):
        return float(value)
    # A decimal comma is only unambiguous when the comma is not the column delimiter.
    if delimiter != "," and _FLOAT_COMMA.fullmatch(value):
        return float(value.replace(",", "."))
    if _ISO_DATE.fullmatch(value):
        try:
            return dt.datetime.fromisoformat(value) if len(value) > 10 else dt.date.fromisoformat(value)
        except ValueError:
            return value
    if match := _FR_DATE.fullmatch(value):
        try:
            return dt.date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            return value
    lowered = value.lower()
    if lowered in ("true", "false", "vrai", "faux"):
        return lowered in ("true", "vrai")
    return value


# --- XLSX (openpyxl read-only: parses the sheet XML incrementally) ---


def _read_xlsx(path: Path, limits: Limits) -> Iterator[SheetStream]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as error:  # openpyxl raises many types for corrupt/encrypted files
        raise UnreadableFile(f"Cannot open the workbook: {error}") from error
    try:
        for sheet in workbook.worksheets:
            # Files often declare a huge bogus dimension: recompute it while reading.
            sheet.reset_dimensions()

            def rows(sheet=sheet) -> Iterator[Row]:
                for record in sheet.iter_rows(values_only=True):
                    if any(cell is not None and cell != "" for cell in record):
                        yield record

            yield SheetStream(name=sheet.title, rows=rows(), hidden=sheet.sheet_state != "visible")
    finally:
        workbook.close()


# --- ODS (own iterparse over content.xml: the usual libraries build the whole DOM) ---

_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TABLE_NS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE, _ROW = _TABLE_NS + "table", _TABLE_NS + "table-row"
_CELLS = (_TABLE_NS + "table-cell", _TABLE_NS + "covered-table-cell")
_P, _SPACE = _TEXT + "p", _TEXT + "s"


def _ods_cell_value(cell: ET.Element):
    kind = cell.get(_OFFICE + "value-type")
    if kind is None:
        return None
    if kind in ("float", "percentage", "currency"):
        raw = cell.get(_OFFICE + "value")
        if raw is None:
            return None
        number = float(raw)
        return int(number) if number.is_integer() and "." not in raw else number
    if kind == "boolean":
        return cell.get(_OFFICE + "boolean-value") == "true"
    if kind == "date":
        raw = cell.get(_OFFICE + "date-value") or ""
        try:
            return dt.datetime.fromisoformat(raw) if "T" in raw else dt.date.fromisoformat(raw)
        except ValueError:
            return raw
    if kind == "time":
        return cell.get(_OFFICE + "time-value")  # ISO-8601 duration, kept as text
    paragraphs = []
    for paragraph in cell.iter(_P):
        parts = [paragraph.text or ""]
        for child in paragraph:
            parts.append(" " * int(child.get(_TEXT + "c", 1)) if child.tag == _SPACE else "".join(child.itertext()))
            parts.append(child.tail or "")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs) or None


def _ods_row(row: ET.Element, max_columns: int) -> Row:
    values: list = []
    for cell in row:
        if cell.tag not in _CELLS:
            continue
        repeat = int(cell.get(_TABLE_NS + "number-columns-repeated", 1))
        # Empty cells repeat up to the sheet's full width (16k columns): only keep the padding a later
        # non-empty cell needs (trailing Nones are dropped below).
        values.extend([_ods_cell_value(cell)] * min(repeat, max_columns))
        if len(values) >= max_columns:
            break
    while values and values[-1] is None:
        values.pop()
    return tuple(values[:max_columns])


def _read_ods(path: Path, limits: Limits) -> Iterator[SheetStream]:
    try:
        archive = zipfile.ZipFile(path)
        content = archive.open("content.xml")
    except (zipfile.BadZipFile, KeyError) as error:
        raise UnreadableFile(f"Not a valid .ods file: {error}") from error
    with archive, content:
        events = ET.iterparse(content, events=("start", "end"))
        stack: list[ET.Element] = []

        def release(element: ET.Element) -> None:
            # Drop a finished row from its parent, or a million-row sheet keeps a million empty shells.
            element.clear()
            if stack:
                stack[-1].remove(element)

        def rows(table: ET.Element) -> Iterator[Row]:
            for event, element in events:
                if event == "start":
                    stack.append(element)
                    continue
                stack.pop()
                if element.tag == _ROW:
                    row = _ods_row(element, limits.max_columns)
                    repeat = int(element.get(_TABLE_NS + "number-rows-repeated", 1))
                    release(element)
                    if row:  # empty rows (incl. the 1M trailing ones many files declare) are skipped
                        for _ in range(min(repeat, limits.max_rows_per_sheet)):
                            yield row
                elif element is table:
                    return

        for event, element in events:
            if event == "start":
                stack.append(element)
                if element.tag == _TABLE:
                    yield SheetStream(name=element.get(_TABLE_NS + "name") or "Sheet", rows=rows(element))
                continue
            stack.pop()
            if element.tag == _ROW:  # left over from a sheet the caller stopped reading: still free it
                release(element)


# --- XLS (legacy; xlrd loads one sheet at a time with on_demand) ---


def _read_xls(path: Path, limits: Limits) -> Iterator[SheetStream]:
    import xlrd

    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
    except Exception as error:
        raise UnreadableFile(f"Cannot open the workbook: {error}") from error
    try:
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)

            def rows(sheet=sheet) -> Iterator[Row]:
                for number in range(sheet.nrows):
                    record = tuple(_xls_value(book, cell) for cell in sheet.row(number))
                    if any(cell is not None and cell != "" for cell in record):
                        yield record

            yield SheetStream(name=sheet.name, rows=rows(), hidden=sheet.visibility != 0)
            book.unload_sheet(index)
    finally:
        book.release_resources()


def _xls_value(book, cell):
    import xlrd

    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
        except (ValueError, OverflowError):
            return cell.value
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(cell.value, "#ERROR")
    if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
        return int(cell.value)
    return cell.value
