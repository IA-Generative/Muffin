import datetime as dt
import os
import time
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.engine import QueryError, TableSpec, listing, run_query
from app.limits import QueryLimits


def spec(tmp_path: Path, ref: str, sheet: str, table: pa.Table, columns: list[dict] | None = None) -> TableSpec:
    path = tmp_path / f"{ref}_{sheet}.parquet"
    pq.write_table(table, path)
    described = columns or [
        {"name": name, "sql_type": str(table.schema.field(name).type)} for name in table.column_names
    ]
    return TableSpec(ref=ref, sheet=sheet, path=path, columns=described)


@pytest.fixture
def sandbox(tmp_path) -> Path:
    path = tmp_path / "sandbox"
    path.mkdir()
    return path


@pytest.fixture
def tables(sandbox) -> list[TableSpec]:
    sales = pa.table(
        {
            "région": ["Nord", "Sud", "Nord", "Est"],
            "montant": [10.5, 20.0, 30.0, 5.0],
            "client_id": [1, 2, 1, 3],
            "jour": [dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 2, 1), dt.date(2024, 2, 2)],
        }
    )
    clients = pa.table({"id": [1, 2, 3], "nom": ["Ann", "Bob", "Cléo"]})
    return [spec(sandbox, "f1", "Ventes", sales), spec(sandbox, "f2", "Clients 2024", clients)]


def query(sql: str, tables, sandbox, **limits):
    return run_query(sql, tables, sandbox, QueryLimits(**limits))


def test_an_aggregate_over_one_sheet(tables, sandbox) -> None:
    result = query(
        'SELECT "région", SUM("montant") AS total FROM f1."Ventes" GROUP BY 1 ORDER BY total DESC', tables, sandbox
    )

    assert [c["name"] for c in result["columns"]] == ["région", "total"]
    assert result["rows"] == [["Nord", 40.5], ["Sud", 20.0], ["Est", 5.0]]
    assert result["truncated"] is False


def test_a_join_across_two_files(tables, sandbox) -> None:
    sql = (
        'SELECT c."nom", SUM(v."montant") AS total FROM f1."Ventes" v JOIN f2."Clients 2024" c '
        'ON c."id" = v."client_id" GROUP BY 1 ORDER BY 1'
    )

    result = query(sql, tables, sandbox)

    assert result["rows"] == [["Ann", 40.5], ["Bob", 20.0], ["Cléo", 5.0]]


def test_with_clauses_and_dates_come_back_as_json_values(tables, sandbox) -> None:
    sql = 'WITH m AS (SELECT MIN("jour") AS first_day FROM f1."Ventes") SELECT first_day FROM m;'

    assert query(sql, tables, sandbox)["rows"] == [["2024-01-01"]]


def test_the_result_is_cut_at_the_row_limit_and_says_so(tables, sandbox) -> None:
    result = query("SELECT * FROM range(1000000)", tables, sandbox, max_rows=5)

    assert [r[0] for r in result["rows"]] == [0, 1, 2, 3, 4]
    assert result["truncated"] is True


def test_an_infinite_query_costs_nothing_thanks_to_the_limit(tables, sandbox) -> None:
    started = time.monotonic()

    result = query("SELECT * FROM range(100000000000)", tables, sandbox, max_rows=3)

    assert len(result["rows"]) == 3 and time.monotonic() - started < 5


def test_long_cells_and_huge_results_are_cut(tables, sandbox) -> None:
    long_cell = query("SELECT repeat('x', 5000) AS t", tables, sandbox, max_cell_chars=50)
    assert len(long_cell["rows"][0][0]) == 51  # 50 characters and the ellipsis
    big = query("SELECT repeat('y', 300) AS t FROM range(100)", tables, sandbox, max_result_chars=2000)
    assert big["truncated"] is True and 0 < len(big["rows"]) < 100


def test_non_json_numbers_become_null(tables, sandbox) -> None:
    result = query("SELECT 'NaN'::DOUBLE AS a, 'inf'::DOUBLE AS b, 1.50::DECIMAL(5,2) AS c", tables, sandbox)

    assert result["rows"] == [[None, None, 1.5]]


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT 1) TO 'out.csv'",
        "ATTACH 'x.db'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "SET enable_external_access=true",
        "PRAGMA database_list",
        "/* hello */ pragma database_list",
        "-- note\nPRAGMA database_list;",
        'DROP VIEW f1."Ventes"',
        "CREATE TABLE t AS SELECT 1",
        'INSERT INTO f1."Ventes" VALUES (1)',
        "EXPLAIN SELECT 1",
        "CALL pragma_database_size()",
    ],
)
def test_only_select_statements_are_accepted(sql, tables, sandbox) -> None:
    with pytest.raises(QueryError, match="SELECT"):
        query(sql, tables, sandbox)


def test_two_statements_are_refused(tables, sandbox) -> None:
    with pytest.raises(QueryError, match="Une seule requête"):
        query("SELECT 1; SELECT 2", tables, sandbox)


def test_a_syntax_error_says_what_is_wrong(tables, sandbox) -> None:
    with pytest.raises(QueryError, match="SQL invalide"):
        query("SELEC 1", tables, sandbox)


def test_an_unknown_table_or_column_is_reported_with_a_hint(tables, sandbox) -> None:
    with pytest.raises(QueryError, match="Ventess"):
        query('SELECT * FROM f1."Ventess"', tables, sandbox)
    with pytest.raises(QueryError, match="montan"):
        query('SELECT "montan" FROM f1."Ventes"', tables, sandbox)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/hostname')",
        "SELECT * FROM read_blob('/etc/hostname')",
        "SELECT * FROM glob('/*')",
        "SELECT * FROM sniff_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM duckdb_secrets()",
        "SELECT * FROM duckdb_extensions()",
    ],
)
def test_nothing_outside_the_listed_tables_can_be_read(sql, tables, sandbox) -> None:
    with pytest.raises(QueryError):
        query(sql, tables, sandbox)


def test_secrets_in_the_environment_and_python_variables_are_out_of_reach(tables, sandbox, monkeypatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "TOPSECRET")
    secret_table = pa.table({"leak": ["python-variable"]})  # noqa: F841 - what a replacement scan would find

    for sql in ("SELECT getenv('AWS_SECRET_ACCESS_KEY')", "SELECT * FROM secret_table"):
        with pytest.raises(QueryError) as error:
            query(sql, tables, sandbox)
        assert "TOPSECRET" not in str(error.value) and "python-variable" not in str(error.value)
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == "TOPSECRET"


def test_a_nested_query_cannot_change_anything(tables, sandbox) -> None:
    with pytest.raises(QueryError):
        query("SELECT * FROM query('DROP VIEW f1.\"Ventes\"')", tables, sandbox)

    assert query('SELECT count(*) FROM f1."Ventes"', tables, sandbox)["rows"] == [[4]]


def test_the_settings_cannot_be_changed_from_inside_a_select(tables, sandbox) -> None:
    with pytest.raises(QueryError):
        query("SELECT * FROM query('SET enable_external_access=true')", tables, sandbox)


def test_a_query_that_runs_too_long_is_interrupted(tables, sandbox) -> None:
    started = time.monotonic()

    with pytest.raises(QueryError, match="interrompue"):
        query("SELECT count(*) FROM range(10000000000) a, range(1000) b", tables, sandbox, timeout_seconds=1)

    assert time.monotonic() - started < 10


def test_a_query_needing_too_much_memory_fails_cleanly(tables, sandbox) -> None:
    with pytest.raises(QueryError, match="mémoire"):
        query(
            "SELECT string_agg(repeat('x', 1000000), ',') FROM range(5000)",
            tables,
            sandbox,
            memory_limit="64MB",
        )


def test_the_listing_names_each_table_as_the_sql_must_write_it(tables) -> None:
    assert [t["table"] for t in listing(tables)] == ['"f1"."Ventes"', '"f2"."Clients 2024"']
    assert listing(tables)[1]["columns"] == [{"name": "id", "type": "int64"}, {"name": "nom", "type": "string"}]


def test_a_sheet_name_with_quotes_is_a_valid_table(sandbox) -> None:
    odd = [spec(sandbox, "f1", 'Chiffres "bruts"', pa.table({"n": [1, 2]}))]

    assert query('SELECT SUM(n) FROM f1."Chiffres ""bruts"""', odd, sandbox)["rows"] == [[3]]


def test_decimal_values_are_floats() -> None:
    from app.engine import _cell

    assert _cell(Decimal("2.50"), QueryLimits()) == 2.5
