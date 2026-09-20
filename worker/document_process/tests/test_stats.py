"""Tests unitaires pour les stats descriptives tabulaires.

Couverture :
- prédicats de type physique (``_is_numeric``, ``_is_date``, ``_is_boolean``,
  ``_is_varchar``) ;
- classification sémantique (``_classify_column``) ;
- sérialisation (``_safe_value``) ;
- sous-fonctions de fetch (``_fetch_base_counts``, ``_fetch_top_values``,
  ``_fetch_numeric_stats``, ``_fetch_date_stats``, ``_fetch_text_stats``) ;
- ``_column_stats`` (intégration légère avec DuckDB) ;
- ``compute_profile`` (intégration légère avec DuckDB) ;
- ``TabularProfile.to_dict``.

Les tests d'intégration créent une vraie table DuckDB en mémoire (pas de mock)
pour valider que les requêtes SQL sont correctes.
"""

from __future__ import annotations

import duckdb
import pytest

from app.tabular import stats
from app.tabular.detect import TabularFormat
from app.tabular.loader import LoadedTable
from app.tabular.stats import (
    ColumnStats,
    SemanticType,
    TabularProfile,
    _classify_column,
    _column_stats,
    _derive_classifications,
    _fetch_base_counts,
    _fetch_date_stats,
    _fetch_numeric_stats,
    _fetch_sample_rows,
    _fetch_schema,
    _fetch_text_stats,
    _fetch_top_values,
    _is_boolean,
    _is_date,
    _is_numeric,
    _is_varchar,
    _safe_value,
    compute_profile,
)

# ---------------------------------------------------------------------------
# Fixtures : vraies tables DuckDB en mémoire
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Connexion DuckDB en mémoire, fermée automatiquement."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def sales_table(conn):
    """Table de ventes avec plusieurs types de colonnes.

    Colonnes :
    - ``id`` (INTEGER, cardinalité = nb de lignes → identifier)
    - ``product`` (VARCHAR, faible cardinalité → dimension)
    - ``price`` (DOUBLE, cardinalité élevée → measure)
    - ``quantity`` (INTEGER, cardinalité élevée → measure)
    - ``in_stock`` (BOOLEAN → boolean)
    - ``description`` (VARCHAR, longueur élevée → text)
    - ``created_at`` (TIMESTAMP → datetime)
    - ``optional_col`` (VARCHAR avec NULLs → dimension)
    """
    conn.execute("""
        CREATE TABLE sales AS
        SELECT * FROM (VALUES
            (1, 'Widget', 19.99::DOUBLE, 100, TRUE,
             repeat('A small widget for everyday use. ', 6),
             TIMESTAMP '2024-01-15 10:30:00', 'A'),
            (2, 'Gadget', 29.50::DOUBLE, 50, FALSE,
             repeat('A medium gadget with many features. ', 6),
             TIMESTAMP '2024-02-20 14:00:00', 'B'),
            (3, 'Widget', 19.99::DOUBLE, 100, TRUE,
             repeat('A small widget for everyday use. ', 6),
             TIMESTAMP '2024-03-10 09:15:00', NULL),
            (4, 'Gizmo', 99.00::DOUBLE, 50, TRUE,
             repeat('A premium gizmo with advanced features. ', 6),
             TIMESTAMP '2024-04-05 16:45:00', 'C'),
            (5, 'Widget', 15.00::DOUBLE, 200, FALSE,
             repeat('A small widget for everyday use. ', 6),
             TIMESTAMP '2024-05-12 11:20:00', 'A')
        ) AS t(id, product, price, quantity, in_stock, description, created_at, optional_col)
    """)
    return "sales"


@pytest.fixture
def empty_table(conn):
    """Table vide avec une seule colonne VARCHAR."""
    conn.execute("CREATE TABLE empty_tbl (name VARCHAR)")
    return "empty_tbl"


@pytest.fixture
def all_null_table(conn):
    """Table avec une colonne entièrement NULL."""
    conn.execute("CREATE TABLE null_tbl (val INTEGER)")
    conn.execute("INSERT INTO null_tbl VALUES (NULL), (NULL), (NULL)")
    return "null_tbl"


def _make_loaded_table(conn, table_name, fmt=TabularFormat.CSV):
    """Crée un ``LoadedTable`` à partir d'une connexion et d'un nom de table."""
    return LoadedTable(connection=conn, format=fmt, table_name=table_name)


# ---------------------------------------------------------------------------
# Prédicats de type physique
# ---------------------------------------------------------------------------


class TestIsNumeric:
    @pytest.mark.parametrize(
        "duckdb_type",
        [
            "BIGINT",
            "INTEGER",
            "SMALLINT",
            "TINYINT",
            "HUGEINT",
            "FLOAT",
            "DOUBLE",
            "DECIMAL(10,2)",
            "REAL",
            "INT",
        ],
    )
    def test_recognizes_numeric_types(self, duckdb_type):
        assert _is_numeric(duckdb_type)

    @pytest.mark.parametrize(
        "duckdb_type",
        ["VARCHAR", "BOOLEAN", "DATE", "TIMESTAMP", "TEXT"],
    )
    def test_rejects_non_numeric_types(self, duckdb_type):
        assert not _is_numeric(duckdb_type)

    def test_case_insensitive(self):
        assert _is_numeric("integer")
        assert _is_numeric("Double")


class TestIsDate:
    @pytest.mark.parametrize("duckdb_type", ["DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIME"])
    def test_recognizes_date_types(self, duckdb_type):
        assert _is_date(duckdb_type)

    @pytest.mark.parametrize("duckdb_type", ["INTEGER", "VARCHAR", "BOOLEAN"])
    def test_rejects_non_date_types(self, duckdb_type):
        assert not _is_date(duckdb_type)


class TestIsBoolean:
    def test_recognizes_boolean(self):
        assert _is_boolean("BOOLEAN")

    def test_rejects_non_boolean(self):
        assert not _is_boolean("INTEGER")
        assert not _is_boolean("VARCHAR")

    def test_case_insensitive(self):
        assert _is_boolean("boolean")


class TestIsVarchar:
    @pytest.mark.parametrize("duckdb_type", ["VARCHAR", "VARCHAR(255)", "CHAR", "CHAR(10)"])
    def test_recognizes_varchar_types(self, duckdb_type):
        assert _is_varchar(duckdb_type)

    @pytest.mark.parametrize("duckdb_type", ["INTEGER", "BOOLEAN", "DATE"])
    def test_rejects_non_varchar_types(self, duckdb_type):
        assert not _is_varchar(duckdb_type)


# ---------------------------------------------------------------------------
# _safe_value
# ---------------------------------------------------------------------------


class TestSafeValue:
    @pytest.mark.parametrize("value", [None, 42, 3.14, "hello", True, False])
    def test_primitives_returned_as_is(self, value):
        assert _safe_value(value) == value

    def test_decimal_is_stringified(self):
        from decimal import Decimal

        result = _safe_value(Decimal("19.99"))
        assert isinstance(result, str)
        assert "19.99" in result

    def test_datetime_is_stringified(self):
        from datetime import datetime

        dt = datetime(2024, 1, 15, 10, 30)
        result = _safe_value(dt)
        assert isinstance(result, str)
        assert "2024" in result

    def test_date_is_stringified(self):
        from datetime import date

        d = date(2024, 1, 15)
        result = _safe_value(d)
        assert isinstance(result, str)
        assert "2024" in result


# ---------------------------------------------------------------------------
# _classify_column
# ---------------------------------------------------------------------------


class TestClassifyColumn:
    def test_boolean_type(self):
        assert _classify_column("BOOLEAN", 2, 5, None) == SemanticType.BOOLEAN

    def test_date_type(self):
        assert _classify_column("DATE", 3, 5, None) == SemanticType.DATETIME

    def test_timestamp_type(self):
        assert _classify_column("TIMESTAMP", 3, 5, None) == SemanticType.DATETIME

    def test_identifier_when_distinct_equals_rows(self):
        # Cardinalité = nb de lignes et > 1 → identifier
        assert _classify_column("INTEGER", 5, 5, None) == SemanticType.IDENTIFIER

    def test_not_identifier_when_single_row(self):
        # distinct_count == 1 ne doit pas être identifier
        assert _classify_column("INTEGER", 1, 1, None) != SemanticType.IDENTIFIER

    def test_numeric_high_cardinality_is_measure(self):
        # ratio = 8/10 = 0.8 >= 0.5 → measure
        assert _classify_column("DOUBLE", 8, 10, None) == SemanticType.MEASURE

    def test_numeric_low_cardinality_is_dimension(self):
        # ratio = 2/10 = 0.2 < 0.5 → dimension
        assert _classify_column("INTEGER", 2, 10, None) == SemanticType.DIMENSION

    def test_numeric_exact_threshold_is_measure(self):
        # ratio = 5/10 = 0.5 >= 0.5 → measure
        assert _classify_column("INTEGER", 5, 10, None) == SemanticType.MEASURE

    def test_varchar_short_text_is_dimension(self):
        text_stats = {"avg_length": 50.0}
        assert _classify_column("VARCHAR", 3, 10, text_stats) == SemanticType.DIMENSION

    def test_varchar_long_text_is_text(self):
        text_stats = {"avg_length": 250.0}
        assert _classify_column("VARCHAR", 8, 10, text_stats) == SemanticType.TEXT

    def test_varchar_at_threshold_is_text(self):
        # avg_length == TEXT_AVG_LENGTH_THRESHOLD (200) → text
        text_stats = {"avg_length": 200.0}
        assert _classify_column("VARCHAR", 8, 10, text_stats) == SemanticType.TEXT

    def test_varchar_no_text_stats_is_dimension(self):
        assert _classify_column("VARCHAR", 3, 10, None) == SemanticType.DIMENSION

    def test_varchar_none_avg_length_is_dimension(self):
        text_stats = {"avg_length": None}
        assert _classify_column("VARCHAR", 3, 10, text_stats) == SemanticType.DIMENSION

    def test_zero_row_count_returns_measure_for_numeric(self):
        # row_count = 0 → ratio = 1.0 (par défaut) → measure pour un numérique
        result = _classify_column("INTEGER", 0, 0, None)
        assert result == SemanticType.MEASURE

    def test_unknown_type_returns_other(self):
        assert _classify_column("BLOB", 3, 10, None) == SemanticType.OTHER

    def test_identifier_takes_precedence_over_measure(self):
        # Cardinalité = nb de lignes → identifier, même si numérique
        assert _classify_column("INTEGER", 10, 10, None) == SemanticType.IDENTIFIER


# ---------------------------------------------------------------------------
# _fetch_base_counts
# ---------------------------------------------------------------------------


class TestFetchBaseCounts:
    def test_returns_total_non_null_and_distinct(self, conn, sales_table):
        # product: 5 rows, 5 non-null, 3 distinct (Widget, Gadget, Gizmo)
        total, non_null, distinct = _fetch_base_counts(conn, sales_table, '"product"')
        assert total == 5
        assert non_null == 5
        assert distinct == 3

    def test_counts_nulls(self, conn, sales_table):
        # optional_col: 5 rows, 4 non-null (A, B, NULL, C, A), 3 distinct (A, B, C)
        total, non_null, distinct = _fetch_base_counts(conn, sales_table, '"optional_col"')
        assert total == 5
        assert non_null == 4
        assert distinct == 3

    def test_empty_table(self, conn, empty_table):
        total, non_null, distinct = _fetch_base_counts(conn, empty_table, '"name"')
        assert total == 0
        assert non_null == 0
        assert distinct == 0

    def test_all_null_column(self, conn, all_null_table):
        total, non_null, distinct = _fetch_base_counts(conn, all_null_table, '"val"')
        assert total == 3
        assert non_null == 0
        assert distinct == 0


# ---------------------------------------------------------------------------
# _fetch_top_values
# ---------------------------------------------------------------------------


class TestFetchTopValues:
    def test_returns_top_n_by_frequency(self, conn, sales_table):
        top = _fetch_top_values(conn, sales_table, '"product"')
        # Widget apparaît 3 fois, Gadget 1, Gizmo 1
        assert len(top) <= stats.TOP_VALUES_LIMIT
        assert top[0]["value"] == "Widget"
        assert top[0]["count"] == 3

    def test_all_values_when_fewer_than_limit(self, conn, sales_table):
        top = _fetch_top_values(conn, sales_table, '"product"')
        # 3 valeurs distinctes, limite = 5 → on en a 3
        assert len(top) == 3

    def test_empty_column_returns_empty(self, conn, empty_table):
        top = _fetch_top_values(conn, empty_table, '"name"')
        assert top == []

    def test_all_null_column_returns_empty(self, conn, all_null_table):
        top = _fetch_top_values(conn, all_null_table, '"val"')
        assert top == []

    def test_values_are_safe(self, conn, sales_table):
        top = _fetch_top_values(conn, sales_table, '"id"')
        for entry in top:
            assert isinstance(entry["value"], (int, float, str, bool))
            assert isinstance(entry["count"], int)


# ---------------------------------------------------------------------------
# _fetch_numeric_stats
# ---------------------------------------------------------------------------


class TestFetchNumericStats:
    def test_returns_min_max_mean_median_stddev(self, conn, sales_table):
        result = _fetch_numeric_stats(conn, sales_table, '"price"')
        assert result is not None
        assert set(result.keys()) == {"min", "max", "mean", "median", "stddev"}
        # prices: 19.99, 29.50, 19.99, 99.00, 15.00
        assert result["min"] == 15.0
        assert result["max"] == 99.0

    def test_returns_none_for_empty_column(self, conn, empty_table):
        # empty_tbl n'a qu'une colonne VARCHAR, mais testons avec une table
        # numérique vide
        conn.execute("CREATE TABLE empty_num (val INTEGER)")
        result = _fetch_numeric_stats(conn, "empty_num", '"val"')
        assert result is None

    def test_returns_none_for_all_null_column(self, conn, all_null_table):
        result = _fetch_numeric_stats(conn, all_null_table, '"val"')
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_date_stats
# ---------------------------------------------------------------------------


class TestFetchDateStats:
    def test_returns_min_max_dates(self, conn, sales_table):
        result = _fetch_date_stats(conn, sales_table, '"created_at"')
        assert result is not None
        assert "min" in result
        assert "max" in result
        # Les dates sont stringifiées
        assert isinstance(result["min"], str)
        assert isinstance(result["max"], str)
        assert "2024" in result["min"]

    def test_returns_none_for_all_null(self, conn, all_null_table):
        result = _fetch_date_stats(conn, all_null_table, '"val"')
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_text_stats
# ---------------------------------------------------------------------------


class TestFetchTextStats:
    def test_returns_min_max_avg_length(self, conn, sales_table):
        result = _fetch_text_stats(conn, sales_table, '"product"')
        assert result is not None
        assert set(result.keys()) == {"min_length", "max_length", "avg_length"}
        # product: Widget(6), Gadget(6), Widget(6), Gizmo(5), Widget(6)
        assert result["min_length"] == 5
        assert result["max_length"] == 6

    def test_returns_none_for_all_null_varchar(self, conn):
        # _fetch_text_stats ne s'appelle que sur des VARCHAR.
        conn.execute("CREATE TABLE null_varchar (val VARCHAR)")
        conn.execute("INSERT INTO null_varchar VALUES (NULL), (NULL), (NULL)")
        result = _fetch_text_stats(conn, "null_varchar", '"val"')
        assert result is None


# ---------------------------------------------------------------------------
# _column_stats (intégration légère)
# ---------------------------------------------------------------------------


class TestColumnStats:
    def test_numeric_column_stats(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "price", "DOUBLE", 5)
        assert col.name == "price"
        assert col.type == "DOUBLE"
        assert col.null_count == 0
        assert col.distinct_count == 4  # 19.99 apparaît 2 fois
        assert col.numeric_stats is not None
        assert col.text_stats is None
        assert col.date_stats is None
        assert len(col.top_values) > 0

    def test_varchar_column_stats(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "product", "VARCHAR", 5)
        assert col.name == "product"
        assert col.null_count == 0
        assert col.distinct_count == 3
        assert col.text_stats is not None
        assert col.numeric_stats is None
        assert col.semantic_type == SemanticType.DIMENSION

    def test_boolean_column_stats(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "in_stock", "BOOLEAN", 5)
        assert col.semantic_type == SemanticType.BOOLEAN
        assert col.numeric_stats is None
        assert col.text_stats is None

    def test_date_column_stats(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "created_at", "TIMESTAMP", 5)
        assert col.semantic_type == SemanticType.DATETIME
        assert col.date_stats is not None
        assert col.numeric_stats is None

    def test_identifier_column(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "id", "INTEGER", 5)
        # id: 5 valeurs distinctes pour 5 lignes → identifier
        assert col.semantic_type == SemanticType.IDENTIFIER
        assert col.distinct_count == 5

    def test_text_column_classification(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "description", "VARCHAR", 5)
        # description a une longueur moyenne > 200 → text
        assert col.semantic_type == SemanticType.TEXT
        assert col.text_stats is not None
        assert col.text_stats["avg_length"] >= stats.TEXT_AVG_LENGTH_THRESHOLD

    def test_column_with_nulls(self, conn, sales_table):
        col = _column_stats(conn, sales_table, "optional_col", "VARCHAR", 5)
        assert col.null_count == 1  # 1 NULL sur 5
        assert col.distinct_count == 3  # A, B, C

    def test_empty_table_column(self, conn, empty_table):
        col = _column_stats(conn, empty_table, "name", "VARCHAR", 0)
        assert col.null_count == 0
        assert col.distinct_count == 0
        assert col.top_values == []
        assert col.text_stats is None
        assert col.numeric_stats is None

    def test_all_null_column(self, conn, all_null_table):
        col = _column_stats(conn, all_null_table, "val", "INTEGER", 3)
        assert col.null_count == 3
        assert col.distinct_count == 0
        assert col.top_values == []
        assert col.numeric_stats is None


# ---------------------------------------------------------------------------
# _fetch_schema
# ---------------------------------------------------------------------------


class TestFetchSchema:
    def test_returns_column_names_and_types(self, conn, sales_table):
        schema = _fetch_schema(conn, sales_table)
        assert len(schema) == 8
        names = [col[0] for col in schema]
        assert "id" in names
        assert "product" in names
        assert "price" in names
        # Chaque entrée est un tuple (nom, type)
        for name, col_type in schema:
            assert isinstance(name, str)
            assert isinstance(col_type, str)

    def test_empty_table_schema(self, conn, empty_table):
        schema = _fetch_schema(conn, empty_table)
        assert len(schema) == 1
        assert schema[0][0] == "name"


# ---------------------------------------------------------------------------
# _fetch_sample_rows
# ---------------------------------------------------------------------------


class TestFetchSampleRows:
    def test_returns_rows_as_dicts(self, conn, sales_table):
        rows = _fetch_sample_rows(conn, sales_table, ["id", "product", "price"])
        assert len(rows) == 5  # 5 rows, limite = 5
        for row in rows:
            assert isinstance(row, dict)
            assert "id" in row
            assert "product" in row
            assert "price" in row

    def test_respects_limit(self, conn):
        conn.execute("CREATE TABLE big_tbl AS SELECT range AS n FROM range(100)")
        rows = _fetch_sample_rows(conn, "big_tbl", ["n"])
        assert len(rows) == stats.SAMPLE_ROWS_LIMIT

    def test_empty_table_returns_empty(self, conn, empty_table):
        rows = _fetch_sample_rows(conn, empty_table, ["name"])
        assert rows == []


# ---------------------------------------------------------------------------
# _derive_classifications
# ---------------------------------------------------------------------------


class TestDeriveClassifications:
    def _col(self, name, semantic_type):
        return ColumnStats(name=name, type="VARCHAR", semantic_type=semantic_type)

    def test_groups_by_semantic_type(self):
        columns = [
            self._col("price", SemanticType.MEASURE),
            self._col("qty", SemanticType.MEASURE),
            self._col("product", SemanticType.DIMENSION),
            self._col("in_stock", SemanticType.BOOLEAN),
            self._col("desc", SemanticType.TEXT),
        ]
        measures, dimensions, text_columns = _derive_classifications(columns)
        assert measures == ["price", "qty"]
        assert dimensions == ["product", "in_stock"]  # BOOLEAN inclus dans dimensions
        assert text_columns == ["desc"]

    def test_empty_columns(self):
        measures, dimensions, text_columns = _derive_classifications([])
        assert measures == []
        assert dimensions == []
        assert text_columns == []

    def test_other_type_not_grouped(self):
        columns = [self._col("blob", SemanticType.OTHER)]
        measures, dimensions, text_columns = _derive_classifications(columns)
        assert measures == []
        assert dimensions == []
        assert text_columns == []


# ---------------------------------------------------------------------------
# compute_profile (intégration légère)
# ---------------------------------------------------------------------------


class TestComputeProfile:
    def test_full_profile(self, conn, sales_table):
        table = _make_loaded_table(conn, sales_table)
        profile = compute_profile(table)

        assert profile.row_count == 5
        assert profile.column_count == 8
        assert profile.format == "csv"
        assert len(profile.columns) == 8
        assert len(profile.sample_rows) == 5

        # Vérifie les classifications dérivées
        assert "price" in profile.measures
        # quantity: 3 distinct (100, 50, 200) pour 5 rows → ratio 0.6 → measure
        assert "quantity" in profile.measures
        assert "product" in profile.dimensions
        assert "in_stock" in profile.dimensions  # BOOLEAN → dimensions
        assert "description" in profile.text_columns
        assert "id" not in profile.measures  # id est identifier, pas measure

    def test_profile_format_matches_table(self, conn, sales_table):
        table = _make_loaded_table(conn, sales_table, fmt=TabularFormat.JSON)
        profile = compute_profile(table)
        assert profile.format == "json"

    def test_profile_empty_table(self, conn, empty_table):
        table = _make_loaded_table(conn, empty_table)
        profile = compute_profile(table)
        assert profile.row_count == 0
        assert profile.column_count == 1
        assert profile.sample_rows == []
        assert profile.measures == []
        # Une colonne VARCHAR vide est classifiée comme dimension par défaut.
        assert profile.dimensions == ["name"]
        assert profile.text_columns == []

    def test_profile_all_null_table(self, conn, all_null_table):
        table = _make_loaded_table(conn, all_null_table)
        profile = compute_profile(table)
        assert profile.row_count == 3
        assert profile.column_count == 1
        col = profile.columns[0]
        assert col.null_count == 3
        assert col.distinct_count == 0
        assert col.top_values == []

    def test_profile_to_dict(self, conn, sales_table):
        table = _make_loaded_table(conn, sales_table)
        profile = compute_profile(table)
        d = profile.to_dict()

        assert d["row_count"] == 5
        assert d["column_count"] == 8
        assert isinstance(d["columns"], list)
        assert len(d["columns"]) == 8
        assert isinstance(d["sample_rows"], list)
        assert d["format"] == "csv"
        assert isinstance(d["measures"], list)
        assert isinstance(d["dimensions"], list)
        assert isinstance(d["text_columns"], list)

    def test_profile_to_dict_column_serializable(self, conn, sales_table):
        """Toutes les valeurs dans to_dict() doivent être JSON-sérialisables."""
        import json

        table = _make_loaded_table(conn, sales_table)
        profile = compute_profile(table)
        d = profile.to_dict()
        # Si une valeur n'est pas sérialisable, json.dumps lèvera TypeError
        json.dumps(d)


# ---------------------------------------------------------------------------
# TabularProfile.to_dict
# ---------------------------------------------------------------------------


class TestTabularProfileToDict:
    def test_to_dict_structure(self):
        col = ColumnStats(
            name="price",
            type="DOUBLE",
            semantic_type="measure",
            null_count=0,
            distinct_count=5,
            top_values=[{"value": 19.99, "count": 2}],
            numeric_stats={
                "min": 15.0,
                "max": 99.0,
                "mean": 36.0,
                "median": 19.99,
                "stddev": 30.0,
            },
        )
        profile = TabularProfile(
            row_count=5,
            column_count=1,
            columns=[col],
            sample_rows=[{"price": 19.99}],
            format="csv",
            measures=["price"],
            dimensions=[],
            text_columns=[],
        )
        d = profile.to_dict()
        assert d["row_count"] == 5
        assert d["column_count"] == 1
        assert d["columns"][0]["name"] == "price"
        assert d["columns"][0]["numeric_stats"]["min"] == 15.0
        assert d["sample_rows"] == [{"price": 19.99}]
        assert d["measures"] == ["price"]
