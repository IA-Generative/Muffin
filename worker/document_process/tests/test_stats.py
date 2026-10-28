"""Tests unitaires pour les types, la classification et le modèle du profil tabulaire.

Couverture :
- prédicats de type physique (``_is_numeric``, ``_is_date``, ``_is_boolean``,
  ``_is_varchar``) ;
- classification sémantique (``_classify_column``, ``_derive_classifications``) ;
- sérialisation (``_safe_value``) ;
- ``TabularProfile.to_dict``.

Le calcul des statistiques lui-même est dans ``app.tabular.sheets`` (testé dans
``test_sheets_*.py``) ; le passage de l'un à l'autre dans ``test_sheets_profile.py``.
"""

from __future__ import annotations

import pytest

from app.tabular.stats import (
    ColumnStats,
    SemanticType,
    TabularProfile,
    _classify_column,
    _derive_classifications,
    _is_boolean,
    _is_date,
    _is_numeric,
    _is_varchar,
    _safe_value,
)

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
