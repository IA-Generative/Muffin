"""From the analysis of a file to what Muffin keeps (app/tabular/sheets/compat.py)."""

import datetime as dt

import pytest
from openpyxl import Workbook

from app.tabular.sheets import compat
from app.tabular.sheets.analyzer import analyze_file
from app.tabular.sheets.limits import Limits
from app.tabular.stats import SemanticType


def _workbook(path, sheets):
    workbook = Workbook(write_only=True)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return path


def _csv(path, header, rows):
    path.write_text(
        ",".join(header) + "\n" + "\n".join(",".join(map(str, row)) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def _columns(profile):
    return {column.name: column for column in profile.columns}


def test_the_profile_has_the_shape_it_always_had(tmp_path):
    # Amounts that repeat a little, as amounts do: 40 different ones would be an identifier (the rule of old).
    rows = [[f"c{i % 4}", i // 2 * 1.5, f"2026-01-{i % 28 + 1:02d}", "x" * (i % 5 + 1)] for i in range(40)]
    path = _csv(tmp_path / "f.csv", ["categorie", "montant", "jour", "libelle"], rows)

    profile = compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv")

    assert (profile.row_count, profile.column_count, profile.format) == (40, 4, "csv")
    columns = _columns(profile)
    assert {n: c.type for n, c in columns.items()} == {
        "categorie": "VARCHAR",
        "montant": "DOUBLE",
        "jour": "DATE",
        "libelle": "VARCHAR",
    }
    assert columns["montant"].semantic_type == SemanticType.MEASURE
    assert columns["categorie"].semantic_type == SemanticType.DIMENSION
    assert columns["jour"].semantic_type == SemanticType.DATETIME
    assert profile.measures == ["montant"] and "categorie" in profile.dimensions
    to_dict = profile.to_dict()
    assert set(to_dict) == {
        "row_count", "column_count", "columns", "sample_rows", "format", "measures", "dimensions", "text_columns",
    }  # fmt: skip


def test_the_statistics_keep_the_names_the_summary_and_the_agent_read(tmp_path):
    path = _csv(tmp_path / "f.csv", ["n", "d", "t"], [[i, f"2026-0{i % 9 + 1}-01", f"mot{i % 3}"] for i in range(30)])

    columns = _columns(compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv"))

    assert set(columns["n"].numeric_stats) == {"min", "max", "mean", "median", "stddev"}
    assert (columns["n"].numeric_stats["min"], columns["n"].numeric_stats["max"]) == (0, 29)
    assert set(columns["d"].date_stats) == {"min", "max"}
    assert set(columns["t"].text_stats) == {"min_length", "max_length", "avg_length"}
    assert columns["t"].top_values[0]["count"] == 10 and set(columns["t"].top_values[0]) == {"value", "count"}
    assert columns["n"].null_count == 0 and columns["n"].distinct_count == 30


def test_the_sample_rows_are_the_first_rows_by_column_name(tmp_path):
    path = _csv(tmp_path / "f.csv", ["a", "b"], [[i, f"v{i}"] for i in range(20)])
    profile = compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv")
    assert profile.sample_rows == [{"a": i, "b": f"v{i}"} for i in range(5)]


def test_a_column_of_free_text_is_a_text_column(tmp_path):
    """Its real length tells it - the analysis cuts a long text for its counts, not for this."""
    long = "mot " * 80
    path = _csv(tmp_path / "f.csv", ["id", "avis", "ville"], [[i, long.strip(), f"v{i % 3}"] for i in range(10)])

    profile = compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv")

    assert profile.text_columns == ["avis"]
    assert _columns(profile)["ville"].semantic_type == SemanticType.DIMENSION


def test_a_column_of_unique_values_is_an_identifier(tmp_path):
    path = _csv(tmp_path / "f.csv", ["id", "v"], [[i, i % 2] for i in range(1, 51)])
    assert _columns(compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv"))["id"].semantic_type == (
        SemanticType.IDENTIFIER
    )


def test_past_a_thousand_distinct_values_a_number_is_still_a_measure_and_never_an_identifier(tmp_path):
    """The analysis stops counting distinct values at max_distinct: 1000 of 5000 would be 'a dimension' by the ratio."""
    path = _csv(tmp_path / "f.csv", ["n", "texte"], [[i * 1.5, f"u{i}"] for i in range(5000)])
    analysis = analyze_file(path, "f.csv", Limits())
    assert analysis["sheets"][0]["columns"][0]["distinct_exact"] is False

    columns = _columns(compat.profile_from_analysis(analysis, "csv"))

    assert columns["n"].semantic_type == SemanticType.MEASURE
    # All 5000 are different, but that cannot be known past the count: not an identifier.
    assert columns["texte"].semantic_type != SemanticType.IDENTIFIER
    assert columns["n"].distinct_count == 1000  # reported as the analysis counted it: a lower bound


def test_a_mixed_column_is_text(tmp_path):
    path = _csv(tmp_path / "f.csv", ["m"], [[1], ["a"], [2], ["b"], [3]])
    column = _columns(compat.profile_from_analysis(analyze_file(path, "f.csv"), "csv"))["m"]
    assert column.type == "VARCHAR"


def test_the_main_sheet_is_the_one_with_the_most_rows(tmp_path):
    path = _workbook(
        tmp_path / "f.xlsx",
        {
            "Petite": [["a"], [1]],
            "Grande": [["b"]] + [[i] for i in range(10)],
            "Autre": [["c"]] + [[i] for i in range(10)],
        },
    )
    analysis = analyze_file(path, "f.xlsx")

    assert compat.primary_sheet(analysis)["name"] == "Grande"  # the first of two equal ones
    profile = compat.profile_from_analysis(analysis, "xlsx")
    assert (profile.primary_sheet, profile.row_count) == ("Grande", 10)
    assert [s["name"] for s in profile.sheets] == ["Petite", "Grande", "Autre"]
    assert profile.sheets[1] == {"name": "Grande", "rows": 10, "columns": ["b"]}


def test_a_sheet_without_rows_is_not_a_sheet_of_the_workbook_for_the_profile(tmp_path):
    path = _workbook(tmp_path / "f.xlsx", {"Vide": [], "Ventes": [["a"], [1]]})
    profile = compat.profile_from_analysis(analyze_file(path, "f.xlsx"), "xlsx")
    assert [s["name"] for s in profile.sheets] == ["Ventes"]


def test_dates_and_booleans_are_typed(tmp_path):
    path = _workbook(
        tmp_path / "f.xlsx",
        {"s": [["jour", "ok"]] + [[dt.datetime(2026, 1, i + 1), i % 2 == 0] for i in range(10)]},
    )
    columns = _columns(compat.profile_from_analysis(analyze_file(path, "f.xlsx"), "xlsx"))
    assert columns["jour"].type == "TIMESTAMP" and columns["jour"].semantic_type == SemanticType.DATETIME
    assert columns["ok"].type == "BOOLEAN" and columns["ok"].semantic_type == SemanticType.BOOLEAN


# --- the sheets the backend keeps ---


def test_each_sheet_is_kept_with_its_analysis_and_where_its_copy_is(tmp_path):
    path = _workbook(tmp_path / "f.xlsx", {"Vide": [], "Ventes": [["a", "b"], [1, "x"], [2, "y"]]})
    analysis = analyze_file(path, "f.xlsx")
    described = {1: {"rows": 2, "columns": [{"name": "a", "sql_type": "BIGINT"}, {"name": "b", "sql_type": "VARCHAR"}]}}

    sheets = compat.sheets_payload(analysis, described, {1: "documents/c/d/tables/1.parquet"})

    assert [s["name"] for s in sheets] == ["Vide", "Ventes"]
    vide, ventes = sheets
    assert (vide["rows"], vide["table"], vide["parquet_key"]) == (0, None, None)
    assert (ventes["index"], ventes["rows"], ventes["header_detected"], ventes["truncated"]) == (1, 2, True, False)
    assert ventes["table"] == described[1] and ventes["parquet_key"] == "documents/c/d/tables/1.parquet"
    assert [c["name"] for c in ventes["columns"]] == ["a", "b"] and ventes["preview"] == [[1, "x"], [2, "y"]]
    assert set(ventes) == {
        "index", "name", "hidden", "rows", "header_detected", "truncated", "columns", "preview", "warnings", "table",
        "parquet_key",
    }  # fmt: skip


def test_the_sheets_are_plain_json(tmp_path):
    import json

    path = _workbook(
        tmp_path / "f.xlsx", {"s": [["jour", "n"], [dt.datetime(2026, 1, 1), 1.5], [dt.datetime(2026, 1, 2), 2.5]]}
    )
    analysis = analyze_file(path, "f.xlsx")
    json.dumps(compat.sheets_payload(analysis, {}, {}))  # raises if anything is not serializable


@pytest.mark.parametrize("version", [compat.ANALYSIS_VERSION])
def test_the_version_of_the_shape_is_an_integer(version):
    assert isinstance(version, int) and version >= 1
