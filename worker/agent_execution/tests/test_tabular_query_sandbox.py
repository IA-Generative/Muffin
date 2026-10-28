"""What the SQL written for a spreadsheet can reach: the table it asks about, and nothing else.

The SQL comes from a model that has read the file, and anyone may have written the file. So these run against a real
DuckDB, the way `execute_tabular_query` uses it: the data is loaded into `source`, the connection is locked, then the
query runs."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import duckdb
import pytest

from app.graph.services import tabular_query
from app.graph.services.tabular_query import (
    MAX_RESULT_ROWS,
    _lock_connection,
    _run_bounded,
    _validate_sql,
    execute_tabular_query,
)


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "ventes.csv"
    path.write_text("region,montant\nNord,10\nSud,20\nNord,30\n", encoding="utf-8")
    return path


@pytest.fixture
def secret_file(tmp_path):
    """A file next to the data, that no query has any business reading."""
    path = tmp_path / "secret.txt"
    path.write_text("not for the model\n", encoding="utf-8")
    return path


@pytest.fixture
def locked(csv_file):
    """A connection as the executor leaves it for the query: the table loaded, the connection locked."""
    connection = duckdb.connect(":memory:")
    connection.execute(f"CREATE TABLE source AS SELECT * FROM read_csv_auto('{csv_file}', header=true)")
    _lock_connection(connection)
    yield connection
    connection.close()


# --- what a query can still do ---


def test_the_table_is_still_there_to_be_queried(locked):
    result = _run_bounded(locked, "SELECT region, SUM(montant) AS total FROM source GROUP BY 1 ORDER BY 1")
    assert result.columns == ["region", "total"] and result.rows == [["Nord", 40], ["Sud", 20]]


def test_a_cte_a_window_and_a_self_join_still_work(locked):
    sql = """
        WITH totals AS (SELECT region, SUM(montant) AS t FROM source GROUP BY 1)
        SELECT a.region, a.t, RANK() OVER (ORDER BY a.t DESC) AS rang FROM totals a JOIN totals b ON a.region = b.region
        ORDER BY rang
    """
    assert _run_bounded(locked, sql).rows == [["Nord", 40, 1], ["Sud", 20, 2]]


def test_the_builtin_functions_that_read_nothing_still_work(locked):
    assert _run_bounded(locked, "SELECT upper('a') AS u, strftime(DATE '2026-01-31', '%d/%m/%Y') AS d").rows == [
        ["A", "31/01/2026"]
    ]


# --- what it can no longer reach ---


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_text('{file}')",
        "SELECT * FROM read_csv('{file}')",
        "SELECT * FROM read_csv_auto('{file}')",
        "SELECT * FROM read_blob('{file}')",
        "SELECT * FROM read_json('{file}')",
        "SELECT * FROM read_parquet('{file}')",
        "SELECT * FROM glob('{folder}/*')",
        "SELECT * FROM glob('s3://any-bucket/*')",
        "SELECT * FROM read_csv('s3://any-bucket/any-object.csv')",
        "SELECT * FROM read_csv('https://example.com/data.csv')",
        "SELECT * FROM '{file}'",
    ],
)
def test_a_query_cannot_read_a_file_or_the_network(locked, secret_file, sql):
    sql = sql.format(file=secret_file, folder=secret_file.parent)
    with pytest.raises(duckdb.Error):
        _run_bounded(locked, sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SET enable_external_access=true",
        "SET lock_configuration=false",
        "SET memory_limit='100GB'",
        "RESET enable_external_access",
        "INSTALL httpfs",
        "ATTACH '{folder}/other.db'",
        "COPY (SELECT 1) TO '{folder}/out.csv'",
        "COPY source TO '{folder}/out.csv'",
        "EXPORT DATABASE '{folder}/export'",
    ],
)
def test_the_connection_cannot_be_reopened_nor_written_out_even_past_the_validator(locked, secret_file, sql):
    """Straight to the connection, as if the validator had missed it: the lock is what holds."""
    with pytest.raises(duckdb.Error):
        locked.execute(sql.format(folder=secret_file.parent))
    assert not list(secret_file.parent.glob("out.csv")) and not (secret_file.parent / "export").exists()


def test_the_settings_still_say_the_connection_is_shut(locked):
    settings = dict(
        locked.execute(
            "SELECT name, value FROM duckdb_settings() "
            "WHERE name IN ('enable_external_access', 'lock_configuration', 'autoload_known_extensions')"
        ).fetchall()
    )
    assert settings == {
        "enable_external_access": "false",
        "lock_configuration": "true",
        "autoload_known_extensions": "false",
    }


def test_the_lock_empties_the_storage_credentials_before_it_shuts_the_connection():
    """Recorded, as the settings of the S3 extension only exist once it is loaded - which needs the network."""
    calls: list[str] = []
    connection = MagicMock()
    connection.execute.side_effect = lambda statement: calls.append(statement)

    _lock_connection(connection)

    assert calls[:4] == [
        "SET s3_access_key_id=''",
        "SET s3_secret_access_key=''",
        "SET s3_session_token=''",
        "SET s3_endpoint=''",
    ]
    assert calls[-2:] == ["SET enable_external_access=false", "SET lock_configuration=true"]
    # Locked last: a setting changed after it would be refused.
    assert calls.index("SET lock_configuration=true") == len(calls) - 1


def test_a_credential_setting_the_extension_does_not_have_does_not_stop_the_lock():
    calls: list[str] = []
    connection = MagicMock()

    def execute(statement):
        if statement.startswith("SET s3_"):
            raise duckdb.CatalogException("unrecognized configuration parameter")
        calls.append(statement)

    connection.execute.side_effect = execute
    _lock_connection(connection)
    assert calls[-1] == "SET lock_configuration=true"


# --- the validator ---


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; COPY (SELECT 1) TO 'x.csv'",
        "SELECT * FROM source; DROP TABLE source",
        "WITH x AS (SELECT 1) SELECT * FROM x; SELECT 2",
    ],
)
def test_more_than_one_statement_is_refused(sql):
    with pytest.raises(ValueError):
        _validate_sql(sql)


@pytest.mark.parametrize("sql", ["SELECT FROM WHERE", "SELECT * FROM (", "SELECT 'unclosed"])
def test_sql_that_does_not_parse_is_refused_before_it_is_run(sql):
    with pytest.raises(ValueError, match="Invalid SQL"):
        _validate_sql(sql)


@pytest.mark.parametrize("sql", ["SELECT 1", "select * from source", "WITH c AS (SELECT 1 a) SELECT a FROM c;"])
def test_a_single_select_is_accepted(sql):
    _validate_sql(sql)


def test_the_from_first_form_is_refused_as_it_always_was():
    """It does not start with SELECT or WITH."""
    with pytest.raises(ValueError, match="Only SELECT/WITH"):
        _validate_sql("FROM source")


def test_loading_an_extension_does_not_open_the_connection_again(locked, secret_file):
    """The validator turns LOAD away; and were it to get through, the connection stays shut."""
    try:
        locked.execute("LOAD httpfs")
    except duckdb.Error:
        pass  # refused: nothing to show
    with pytest.raises(duckdb.Error):
        locked.execute("SELECT * FROM read_csv('https://example.com/data.csv')").fetchall()
    with pytest.raises(duckdb.Error):
        locked.execute(f"SELECT * FROM read_text('{secret_file}')").fetchall()
    with pytest.raises(ValueError):
        _validate_sql("LOAD httpfs")


# --- bounded ---


def test_a_big_result_is_counted_whole_and_kept_to_the_cap(csv_file):
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE source AS SELECT range AS n FROM range(10000)")
    _lock_connection(connection)
    result = _run_bounded(connection, "SELECT n FROM source ORDER BY n")
    assert result.row_count == 10000 and result.truncated and len(result.rows) == MAX_RESULT_ROWS
    assert result.rows[0] == [0] and result.rows[-1] == [MAX_RESULT_ROWS - 1]


def test_a_small_result_is_not_truncated(locked):
    result = _run_bounded(locked, "SELECT * FROM source")
    assert (result.row_count, result.truncated, len(result.rows)) == (3, False, 3)


def test_a_query_that_never_ends_is_interrupted(monkeypatch):
    monkeypatch.setattr(tabular_query, "QUERY_TIMEOUT_SECONDS", 1)
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE source AS SELECT 1 AS a")
    _lock_connection(connection)
    with pytest.raises(TimeoutError, match="took more than 1 seconds"):
        _run_bounded(connection, "SELECT SUM(a.range * b.range) FROM range(100000000) a, range(100000000) b")
    # The connection is still usable: the query was stopped, not the worker.
    assert _run_bounded(connection, "SELECT 1 AS one").rows == [[1]]


# --- the executor, as a whole ---


@pytest.fixture
def executor(monkeypatch, csv_file):
    """execute_tabular_query on a local file in place of an S3 object: the same steps, in the same order."""

    @contextmanager
    def connection():
        conn = duckdb.connect(":memory:")
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(tabular_query, "_duckdb_connection", connection)
    monkeypatch.setattr(
        tabular_query,
        "_load_statement",
        lambda format, url: f"CREATE TABLE source AS SELECT * FROM read_csv_auto('{csv_file}', header=true)",
    )
    return lambda sql: execute_tabular_query("documents/c/d.csv", "csv", sql)


def test_the_file_is_loaded_before_the_connection_is_shut(executor):
    """If the lock came first, the load would be refused: this is what pins the order."""
    result = executor("SELECT region, SUM(montant) AS total FROM source GROUP BY 1 ORDER BY 1")
    assert result.rows == [["Nord", 40], ["Sud", 20]] and result.row_count == 2 and not result.truncated


def test_the_executor_refuses_what_reads_a_file_whatever_the_model_was_told(executor, secret_file):
    with pytest.raises(duckdb.Error):
        executor(f"SELECT * FROM read_text('{secret_file}')")
    with pytest.raises(duckdb.Error):
        executor(f"SELECT * FROM glob('{secret_file.parent}/*')")


def test_the_executor_refuses_what_is_not_one_select(executor):
    with pytest.raises(ValueError):
        executor("SELECT 1; SELECT 2")
    with pytest.raises(ValueError):
        executor("COPY source TO 'x.csv'")


def test_a_model_that_wrote_a_query_that_never_ends_gets_an_error_not_a_hung_worker(executor, monkeypatch):
    monkeypatch.setattr(tabular_query, "QUERY_TIMEOUT_SECONDS", 1)
    with pytest.raises(TimeoutError):
        executor("SELECT SUM(a.range * b.range) FROM range(100000000) a, range(100000000) b")
