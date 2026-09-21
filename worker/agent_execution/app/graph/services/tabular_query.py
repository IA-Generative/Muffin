"""Tabular data analysis tool for the research agent.

Loads a tabular file (CSV/XLSX/Parquet/JSON) into an in-process DuckDB
connection and runs an LLM-generated SQL query against it - lets the agent
answer analytical questions (aggregations, filters, counts) that vector search
over text chunks fundamentally can't.

The flow:
1. The backend provides the document's tabular profile (schema, column types,
   classification) via ``GET /internal/users/{user_id}/collections/{id}/tabular-documents``.
2. This service builds a prompt from the profile + the user's question, asks
   the LLM to generate a read-only SELECT query, and executes it in DuckDB.
3. The results are formatted as a markdown table and returned as evidence.

Security:
- Only SELECT statements are allowed - the SQL is validated before execution
  (no INSERT/UPDATE/DELETE/DDL/DROP).
- DuckDB runs in-memory with a hard memory limit and is closed immediately
  after the query, same pattern as worker/document_process.
- The file is read directly from RustFS/S3 via DuckDB's httpfs extension,
  never downloaded to disk.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import duckdb
from loguru import logger

from app.config import settings
from app.graph.services.llm import json_chat

# Same limits as worker/document_process - a research agent run can spawn
# several tabular_query tasks in parallel, so we keep DuckDB's footprint
# bounded per task.
DUCKDB_MEMORY_LIMIT = "2GB"
DUCKDB_THREADS = 2
# Hard cap on rows returned - prevents a pathological query (e.g. SELECT *
# on a million-row table) from flooding the LLM context and the evidence store.
MAX_RESULT_ROWS = 100


@dataclass
class TabularResult:
    """Result of a tabular query execution."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


_SQL_GEN_SYSTEM_PROMPT = (
    "You are a SQL expert. Given a table schema and a natural language question, generate a "
    "single DuckDB SELECT query that answers it. Respond only with JSON: "
    '{"sql": string, "explanation": string}.\n\n'
    "Rules:\n"
    "- Only SELECT statements. No INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or PRAGMA.\n"
    "- Use DuckDB SQL dialect (e.g. LISTAGG, QUANTILE_CONT, date functions).\n"
    "- The table name is always 'source'.\n"
    "- Quote column names with double quotes if they contain spaces or special characters.\n"
    "- Limit results to 100 rows unless the question explicitly asks for more.\n"
    "- If the question can't be answered from the schema, return sql=null.\n"
    "\n"
    "Handling nulls and type conversions:\n"
    '- CSV files may contain the literal string "Null", "null", "NULL", "N/A", "" (empty) or '
    '"None" to represent missing values. These are NOT real SQL NULLs - they are text.\n'
    "- Use TRY_CAST instead of CAST for type conversions. TRY_CAST returns NULL on failure "
    'instead of raising an error. Example: TRY_CAST(TRIM("col") AS DOUBLE).\n'
    "- For numeric columns that may contain null-like strings, always filter them out or use "
    'TRY_CAST. Example: WHERE TRY_CAST(TRIM("col") AS DOUBLE) IS NOT NULL.\n'
    "- Prefer DOUBLE over BIGINT/INT for numeric columns that may contain decimals.\n"
    "- Use TRIM() around string columns before casting to remove whitespace.\n"
    "- For aggregations (AVG, SUM, MAX, MIN), use TRY_CAST to convert the column first, and "
    'filter out NULLs: AVG(TRY_CAST(TRIM("col") AS DOUBLE)) or '
    'MAX(TRY_CAST(TRIM("col") AS DOUBLE)).\n'
)


def _format_schema(profile: dict[str, Any]) -> str:
    """Formats the tabular profile's column list as a readable schema for the LLM."""
    lines = []
    for col in profile.get("columns", []):
        name = col.get("name", "?")
        dtype = col.get("type", "?")
        semantic = col.get("semantic_type", "other")
        null_count = col.get("null_count", 0)
        distinct_count = col.get("distinct_count", 0)
        parts = [f'"{name}" {dtype}']
        if semantic != "other":
            parts.append(f"[{semantic}]")
        parts.append(f"nulls={null_count}")
        parts.append(f"distinct={distinct_count}")
        # Top values for categorical columns help the LLM write better WHERE clauses.
        top_values = col.get("top_values", [])
        if top_values:
            values_str = ", ".join(str(v.get("value", v)) for v in top_values[:5])
            parts.append(f"top=[{values_str}]")
        lines.append("  ".join(parts))
    classification = []
    if profile.get("measures"):
        classification.append(f"measures: {profile['measures']}")
    if profile.get("dimensions"):
        classification.append(f"dimensions: {profile['dimensions']}")
    if profile.get("text_columns"):
        classification.append(f"text_columns: {profile['text_columns']}")
    header = f"Table: source ({profile.get('row_count', '?')} rows, {profile.get('column_count', '?')} columns)"
    if classification:
        header += "\n" + "\n".join(classification)
    return header + "\n\nColumns:\n" + "\n".join(lines)


def _build_sql_gen_prompt(profile: dict[str, Any], question: str) -> str:
    return f"Question: {question}\n\nSchema:\n{_format_schema(profile)}"


def _validate_sql(sql: str) -> None:
    """Rejects any statement that isn't a read-only SELECT.

    DuckDB itself doesn't enforce read-only mode on a connection, so we do a
    lightweight check on the first keyword. This is not a full SQL parser -
    it's a defense against the LLM generating destructive statements, not
    against a malicious actor (the LLM is the only one writing SQL here).
    """
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("Empty SQL query")
    first_word = stripped.split()[0].upper()
    allowed = {"SELECT", "WITH"}
    if first_word not in allowed:
        raise ValueError(f"Only SELECT/WITH queries are allowed, got: {first_word}")
    # Catch subqueries that try to sneak in DML after a WITH CTE.
    upper = stripped.upper()
    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "DROP ",
        "ALTER ",
        "CREATE ",
        "PRAGMA ",
        "ATTACH ",
        "DETACH ",
    )
    for kw in forbidden:
        if kw in upper:
            raise ValueError(f"Forbidden keyword in query: {kw.strip()}")


def _format_results(result: TabularResult) -> str:
    """Formats the query results as a markdown table for the evidence content."""
    if not result.columns:
        return "Query returned no columns."
    header = "| " + " | ".join(result.columns) + " |"
    separator = "| " + " | ".join("---" for _ in result.columns) + " |"
    lines = [header, separator]
    for row in result.rows:
        lines.append("| " + " | ".join(str(v) if v is not None else "" for v in row) + " |")
    if result.truncated:
        lines.append(f"\n*(Results truncated to {MAX_RESULT_ROWS} rows out of {result.row_count})*")
    else:
        lines.append(f"\n*({result.row_count} row{'s' if result.row_count != 1 else ''})*")
    return "\n".join(lines)


@contextmanager
def _duckdb_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """Creates a short-lived in-memory DuckDB connection configured for S3 access."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"PRAGMA memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        connection.execute(f"PRAGMA threads={DUCKDB_THREADS}")
        # Load httpfs (pre-installed in Docker image for readOnlyRootFilesystem).
        # Falls back to INSTALL in dev where extensions aren't pre-installed.
        try:
            connection.execute("LOAD httpfs")
        except duckdb.IOException:
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")
        endpoint = settings.AWS_ENDPOINT_URL.replace("http://", "").replace("https://", "")
        connection.execute(f"SET s3_endpoint='{endpoint}'")
        connection.execute(f"SET s3_access_key_id='{settings.AWS_ACCESS_KEY_ID}'")
        connection.execute(f"SET s3_secret_access_key='{settings.AWS_SECRET_ACCESS_KEY}'")
        connection.execute("SET s3_url_style='path'")
        # RustFS runs on plain HTTP in dev - DuckDB defaults to HTTPS which causes
        # SSL connect errors. Disable SSL when the endpoint is not HTTPS.
        if not settings.AWS_ENDPOINT_URL.startswith("https://"):
            connection.execute("SET s3_use_ssl=false")
        yield connection
    finally:
        connection.close()


def _load_statement(format: str, s3_url: str) -> str:
    """Builds the SQL that loads the file into a DuckDB table named 'source'."""
    format = format.lower()
    if format == "csv":
        return f"CREATE TABLE source AS SELECT * FROM read_csv_auto('{s3_url}', header=true)"
    if format == "tsv":
        return f"CREATE TABLE source AS SELECT * FROM read_csv_auto('{s3_url}', delim='\\t', header=true)"
    if format == "psv":
        return f"CREATE TABLE source AS SELECT * FROM read_csv_auto('{s3_url}', delim='|', header=true)"
    if format == "parquet":
        return f"CREATE TABLE source AS SELECT * FROM read_parquet('{s3_url}')"
    if format in ("json", "jsonl"):
        return f"CREATE TABLE source AS SELECT * FROM read_json_auto('{s3_url}')"
    if format == "xlsx":
        connection_setup = "INSTALL spatial; LOAD spatial;"
        return connection_setup + f" CREATE TABLE source AS SELECT * FROM st_read('{s3_url}', layer=0)"
    raise ValueError(f"Unsupported tabular format: {format}")


def execute_tabular_query(
    storage_key: str,
    format: str,
    sql: str,
) -> TabularResult:
    """Loads a tabular file in DuckDB and executes a SELECT query against it.

    The SQL is expected to be pre-validated (generated by the LLM and checked
    by ``_validate_sql``). Returns the raw results for the caller to format.
    """
    s3_url = f"s3://{settings.AWS_BUCKET}/{storage_key}"
    with _duckdb_connection() as conn:
        load_sql = _load_statement(format, s3_url)
        # XLSX needs the spatial extension loaded before the CREATE TABLE.
        if format.lower() == "xlsx":
            conn.execute("INSTALL spatial")
            conn.execute("LOAD spatial")
        conn.execute(load_sql)
        _validate_sql(sql)
        logger.info(f"Executing tabular query on {storage_key}: {sql[:200]}")
        query_result = conn.execute(sql)
        columns = [desc[0] for desc in query_result.description] if query_result.description else []
        all_rows = query_result.fetchall()
        total = len(all_rows)
        truncated = total > MAX_RESULT_ROWS
        rows = [list(row) for row in all_rows[:MAX_RESULT_ROWS]]
        return TabularResult(
            columns=columns,
            rows=rows,
            row_count=total,
            truncated=truncated,
        )


def generate_sql(
    profile: dict[str, Any],
    question: str,
    model: str,
) -> str | None:
    """Asks the LLM to generate a DuckDB SELECT query from the profile + question.

    Uses ``json_chat`` (the codebase's standard LLM helper) which handles code-fence
    stripping and JSON parsing. Returns None if the LLM couldn't generate a valid query.
    """
    parsed = json_chat(
        model,
        _SQL_GEN_SYSTEM_PROMPT,
        _build_sql_gen_prompt(profile, question),
        fallback=None,
    )
    if not isinstance(parsed, dict):
        return None
    sql = parsed.get("sql")
    if not sql:
        return None
    try:
        _validate_sql(sql)
    except ValueError as error:
        logger.warning(f"LLM-generated SQL failed validation: {error}")
        return None
    return sql


def format_tabular_evidence(
    question: str,
    sql: str,
    result: TabularResult,
    document_name: str,
) -> str:
    """Builds the evidence content string from the query results."""
    return (
        f"**Question:** {question}\n\n"
        f"**SQL query:**\n```sql\n{sql}\n```\n\n"
        f"**Results:**\n{_format_results(result)}\n\n"
        f"*(Source: {document_name})*"
    )
