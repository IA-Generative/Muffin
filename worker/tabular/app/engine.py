"""Runs one SQL query over the Parquet copies of sheets, in a sandbox.

Adapted from spreadsheet-analyser (Apache-2.0, analysis-worker/app/query/engine.py).

The SQL is written by a language model, so nothing in it is trusted:
- exactly one statement, and it must be a SELECT (no COPY, ATTACH, INSTALL, SET, PRAGMA, DDL, DML...);
- DuckDB is locked before the query runs: no file or network access outside the query's own temporary directory
  (which holds only the Parquet of the files the query was authorised for), and the settings cannot be changed;
- memory, threads, run time and result size are bounded.

Each file is a schema named after its reference (f1, f2...) and each sheet a view in it, so joins across files read
naturally: `SELECT ... FROM f1."Ventes" v JOIN f2."Clients" c ON c."id" = v."client_id"`."""

import datetime as dt
import decimal
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.limits import QueryLimits


class QueryError(Exception):
    """The query cannot run or failed: the message is for whoever wrote the SQL (here, the agent) to fix it."""


@dataclass
class TableSpec:
    ref: str  # the schema: f1
    sheet: str  # the view: "Ventes"
    path: Path  # local Parquet
    columns: list[dict]  # [{"name", "sql_type"}], for the listing given back with errors


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(value: object) -> str:
    """A string literal (a path of ours: the quotes are doubled anyway)."""
    return "'" + str(value).replace("'", "''") + "'"


def qualified(spec: TableSpec) -> str:
    return f"{quote(spec.ref)}.{quote(spec.sheet)}"


def listing(tables: list[TableSpec]) -> list[dict]:
    """What can be queried, for an error message: each table as the SQL must name it, with its columns."""
    return [
        {"table": qualified(t), "columns": [{"name": c["name"], "type": c["sql_type"]} for c in t.columns]}
        for t in tables
    ]


def _connect(tables: list[TableSpec], work_dir: Path, limits: QueryLimits) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(f"SET memory_limit='{limits.memory_limit}'")
    connection.execute(f"SET threads={int(limits.threads)}")
    connection.execute("SET autoinstall_known_extensions=false")
    connection.execute("SET autoload_known_extensions=false")
    connection.execute(f"SET temp_directory={_literal(work_dir / 'spill')}")
    for schema in dict.fromkeys(t.ref for t in tables):
        connection.execute(f"CREATE SCHEMA {quote(schema)}")
    for table in tables:
        connection.execute(f"CREATE VIEW {qualified(table)} AS SELECT * FROM read_parquet({_literal(table.path)})")
    # Lock last: the views above needed file access, the query itself must not have any.
    connection.execute(f"SET allowed_directories=[{_literal(work_dir)}]")
    connection.execute("SET enable_external_access=false")
    connection.execute("SET lock_configuration=true")
    return connection


# Leading whitespace and comments, then PRAGMA.
_PRAGMA = re.compile(r"(\s|--[^\n]*(\n|$)|/\*.*?\*/)*pragma\b", re.IGNORECASE | re.DOTALL)


def _single_select(connection: duckdb.DuckDBPyConnection, sql: str) -> str:
    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as error:
        raise QueryError(f"SQL invalide : {_message(error)}") from error
    if len(statements) != 1:
        raise QueryError("Une seule requête à la fois (une instruction SELECT).")
    # DuckDB rewrites `PRAGMA x` into a SELECT over a table function (and hands that text over): it is not a read
    # of the data, so refuse it on what was written.
    if statements[0].type != duckdb.StatementType.SELECT or _PRAGMA.match(sql):
        raise QueryError("Seules les requêtes de lecture (SELECT, éventuellement avec WITH) sont autorisées.")
    return statements[0].query.strip().rstrip(";").strip()


def _message(error: Exception) -> str:
    """DuckDB errors read 'Binder Error: ...\\n\\nLINE 1: ...': keep the first paragraph, plus its hint."""
    text = str(error).strip()
    first, _, rest = text.partition("\n\n")
    hint = next((line for line in rest.splitlines() if line.startswith("Did you mean")), "")
    return f"{first} {hint}".strip()


def _cell(value, limits: QueryLimits):
    """A value as JSON would carry it (the result travels as JSON through the backend)."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, bytes):
        return value[:32].hex()
    if isinstance(value, list | tuple):
        return [_cell(item, limits) for item in value[:50]]
    if isinstance(value, dict):
        return {str(key): _cell(item, limits) for key, item in list(value.items())[:50]}
    text = str(value)
    return text if len(text) <= limits.max_cell_chars else text[: limits.max_cell_chars] + "…"


def run_query(sql: str, tables: list[TableSpec], work_dir: Path, limits: QueryLimits | None = None) -> dict:
    """Result: {"columns": [{"name", "type"}], "rows": [[...]], "truncated": bool}. `truncated` means that the
    query had more rows (or more text) than are given back. Raises QueryError for anything the author of the SQL
    can act on."""
    limits = limits or QueryLimits()
    (work_dir / "spill").mkdir(parents=True, exist_ok=True)
    connection = None
    timer = None
    try:
        connection = _connect(tables, work_dir, limits)
        timer = threading.Timer(limits.timeout_seconds, connection.interrupt)
        statement = _single_select(connection, sql)
        timer.start()
        # The LIMIT is part of the query: DuckDB stops producing rows once it has enough.
        cursor = connection.execute(f"SELECT * FROM ({statement}) LIMIT {limits.max_rows + 1}")
        columns = [{"name": name, "type": str(kind)} for name, kind, *_ in cursor.description]
        fetched = cursor.fetchall()
    except QueryError:
        raise
    except duckdb.InterruptException as error:
        raise QueryError(f"Requête interrompue : plus de {limits.timeout_seconds:g} secondes.") from error
    except duckdb.OutOfMemoryException as error:
        raise QueryError("Requête trop gourmande en mémoire : filtrez ou agrégez davantage.") from error
    except duckdb.PermissionException as error:
        raise QueryError("Accès refusé : seules les tables listées sont lisibles.") from error
    except duckdb.Error as error:
        raise QueryError(_message(error)) from error
    finally:
        if timer is not None:
            timer.cancel()
        if connection is not None:
            connection.close()

    truncated = len(fetched) > limits.max_rows
    rows, size = [], 0
    for record in fetched[: limits.max_rows]:
        row = [_cell(value, limits) for value in record]
        size += sum(len(str(value)) for value in row)
        if size > limits.max_result_chars:
            truncated = True
            break
        rows.append(row)
    return {"columns": columns, "rows": rows, "truncated": truncated}
