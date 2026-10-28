"""What Muffin keeps of the analysis of a file (`analyze_file`): its own profile, and the content of each sheet.

Two shapes come out of one analysis:

- the **profile of the document** (`TabularProfile`, `document_tabular_profile`): the shape Muffin has always had -
  columns with a semantic type, a few top values, a sample of rows, the measures / dimensions / text columns - computed
  on the document's **main sheet** (the one with the most rows). The summary, the generated questions and the agent
  that writes SQL read this, and keep working unchanged;
- the **sheets** (`document_tabular_sheets`): the analysis as it is, one entry per sheet, with where its typed
  Parquet copy is. This is what the file's screen shows and what the agent that queries the data will be built on."""

import math
from typing import Any

from app.tabular.sheets.tables import sql_type
from app.tabular.stats import (
    DIMENSION_CARDINALITY_RATIO,
    SAMPLE_ROWS_LIMIT,
    TOP_VALUES_LIMIT,
    ColumnStats,
    TabularProfile,
    classify_column,
    derive_classifications,
)

# Of the shape sent to the backend (`sheets`): raised when it changes in a way the readers of the former one cannot
# follow. Not the analysis' own `schema_version`, which is that of `analyse.json`.
ANALYSIS_VERSION = 1


def primary_sheet(analysis: dict) -> dict | None:
    """The sheet the profile of the document describes: the one with the most rows (the first, on a tie)."""
    candidates = [sheet for sheet in analysis["sheets"] if sheet["rows"] and sheet["columns"]]
    return max(candidates, key=lambda sheet: sheet["rows"], default=None)


def _distinct_for_classification(column: dict, rows: int) -> int:
    """The number of distinct values to classify a column by. Past `max_distinct` the analysis stops counting them
    (`distinct_exact` is false and `distinct` a lower bound): such a column has *many* - a measure, if it holds numbers
    - but not provably *all* of them, so it is never taken for an identifier."""
    distinct = column["distinct"]
    if column.get("distinct_exact", True) or rows <= 1:
        return distinct
    return min(max(distinct, math.ceil(DIMENSION_CARDINALITY_RATIO * rows)), rows - 1)


def column_stats(column: dict, rows: int) -> ColumnStats:
    """A column of the analysis as one of the profile of the document."""
    column_type = sql_type(column)
    numeric, dates, text = column.get("numeric"), column.get("dates"), column.get("text")
    text_stats = (
        {"min_length": text["min_length"], "max_length": text["max_length"], "avg_length": text.get("avg_length")}
        if text
        else None
    )
    return ColumnStats(
        name=column["name"],
        type=column_type,
        semantic_type=classify_column(column_type, _distinct_for_classification(column, rows), rows, text_stats),
        null_count=column["null"],
        distinct_count=column["distinct"],
        top_values=[
            {"value": entry["value"], "count": entry["count"]}
            for entry in column.get("top_values", [])[:TOP_VALUES_LIMIT]
        ],
        numeric_stats=(
            {
                "min": numeric["min"],
                "max": numeric["max"],
                "mean": numeric["mean"],
                "median": numeric["median"],
                "stddev": numeric["std"],
            }
            if numeric
            else None
        ),
        date_stats={"min": dates["min"], "max": dates["max"]} if dates else None,
        text_stats=text_stats,
    )


def profile_from_analysis(analysis: dict, format_: str) -> TabularProfile:
    """The profile of the document, from the analysis of its main sheet. Raises ValueError for a file with no data."""
    sheet = primary_sheet(analysis)
    if sheet is None:
        raise ValueError("The file contains no data")
    columns = [column_stats(column, sheet["rows"]) for column in sheet["columns"]]
    names = [column["name"] for column in sheet["columns"]]
    measures, dimensions, text_columns = derive_classifications(columns)
    return TabularProfile(
        row_count=sheet["rows"],
        column_count=len(columns),
        columns=columns,
        sample_rows=[dict(zip(names, row, strict=False)) for row in sheet["preview"][:SAMPLE_ROWS_LIMIT]],
        format=format_,
        measures=measures,
        dimensions=dimensions,
        text_columns=text_columns,
        primary_sheet=sheet["name"],
        sheets=[
            {"name": other["name"], "rows": other["rows"], "columns": [column["name"] for column in other["columns"]]}
            for other in analysis["sheets"]
            if other["rows"] and other["columns"]
        ],
    )


def sheets_payload(analysis: dict, described: dict[int, dict], parquet_keys: dict[int, str]) -> list[dict[str, Any]]:
    """The sheets as the backend keeps them: the analysis of each, and where its typed copy is (`table`, with the SQL
    type of each column, and `parquet_key`) - None for a sheet that has no rows to copy."""
    return [
        {
            "index": sheet["index"],
            "name": sheet["name"],
            "hidden": sheet["hidden"],
            "rows": sheet["rows"],
            "header_detected": sheet["header_detected"],
            "truncated": sheet["truncated"],
            "columns": sheet["columns"],
            "preview": sheet["preview"],
            "warnings": sheet["warnings"],
            "table": described.get(sheet["index"]),
            "parquet_key": parquet_keys.get(sheet["index"]),
        }
        for sheet in analysis["sheets"]
    ]
