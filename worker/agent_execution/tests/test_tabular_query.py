"""Unit tests for the tabular_query service.

These tests cover the pure-logic parts (SQL validation, schema formatting, evidence
formatting, SQL generation via mocked LLM) without touching DuckDB or S3. The
execute_tabular_query function is tested separately because it needs a real DuckDB
connection (and a file to load).
"""

import json
from unittest.mock import patch

import pytest

from app.graph.services.tabular_query import (
    TabularResult,
    _build_sql_gen_prompt,
    _format_results,
    _format_schema,
    _validate_sql,
    format_tabular_evidence,
    generate_sql,
)

# ─── _validate_sql ───────────────────────────────────────────────────────────


class TestValidateSql:
    def test_select_is_allowed(self):
        _validate_sql("SELECT * FROM source")
        _validate_sql("select count(*) from source")
        _validate_sql("  WITH cte AS (SELECT 1) SELECT * FROM cte  ")

    def test_empty_sql_raises(self):
        with pytest.raises(ValueError, match="Empty SQL"):
            _validate_sql("")
        with pytest.raises(ValueError, match="Empty SQL"):
            _validate_sql("   ")

    def test_insert_is_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT/WITH"):
            _validate_sql("INSERT INTO source VALUES (1)")

    def test_update_is_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT/WITH"):
            _validate_sql("UPDATE source SET x = 1")

    def test_delete_is_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT/WITH"):
            _validate_sql("DELETE FROM source")

    def test_drop_is_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT/WITH"):
            _validate_sql("DROP TABLE source")

    def test_create_is_rejected(self):
        with pytest.raises(ValueError, match="Only SELECT/WITH"):
            _validate_sql("CREATE TABLE foo AS SELECT 1")

    def test_forbidden_keyword_in_subquery_is_rejected(self):
        # A WITH CTE that tries to sneak in a DROP
        sql = "WITH x AS (SELECT 1) DROP TABLE source"
        with pytest.raises(ValueError, match="Forbidden keyword"):
            _validate_sql(sql)

    def test_trailing_semicolon_is_stripped(self):
        _validate_sql("SELECT * FROM source;")


# ─── _format_schema ──────────────────────────────────────────────────────────


class TestFormatSchema:
    def test_basic_column(self):
        profile = {
            "row_count": 100,
            "column_count": 2,
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "semantic_type": "identifier",
                    "null_count": 0,
                    "distinct_count": 100,
                },
                {
                    "name": "name",
                    "type": "VARCHAR",
                    "semantic_type": "other",
                    "null_count": 5,
                    "distinct_count": 95,
                },
            ],
        }
        result = _format_schema(profile)
        assert "Table: source (100 rows, 2 columns)" in result
        assert '"id" INTEGER' in result
        assert "[identifier]" in result
        assert '"name" VARCHAR' in result
        assert "nulls=0" in result
        assert "distinct=100" in result

    def test_top_values_for_categorical(self):
        profile = {
            "row_count": 10,
            "column_count": 1,
            "columns": [
                {
                    "name": "status",
                    "type": "VARCHAR",
                    "semantic_type": "category",
                    "null_count": 0,
                    "distinct_count": 3,
                    "top_values": [
                        {"value": "active", "count": 5},
                        {"value": "closed", "count": 3},
                        {"value": "pending", "count": 2},
                    ],
                },
            ],
        }
        result = _format_schema(profile)
        assert "top=[active, closed, pending]" in result

    def test_classification_fields(self):
        profile = {
            "row_count": 100,
            "column_count": 3,
            "columns": [],
            "measures": ["amount", "quantity"],
            "dimensions": ["category", "region"],
            "text_columns": ["description"],
        }
        result = _format_schema(profile)
        assert "measures: ['amount', 'quantity']" in result
        assert "dimensions: ['category', 'region']" in result
        assert "text_columns: ['description']" in result


# ─── _format_results ─────────────────────────────────────────────────────────


class TestFormatResults:
    def test_basic_table(self):
        result = TabularResult(
            columns=["name", "count"],
            rows=[["alpha", 10], ["beta", 20]],
            row_count=2,
            truncated=False,
        )
        formatted = _format_results(result)
        assert "| name | count |" in formatted
        assert "| alpha | 10 |" in formatted
        assert "| beta | 20 |" in formatted
        assert "(2 rows)" in formatted

    def test_single_row_grammar(self):
        result = TabularResult(
            columns=["x"],
            rows=[[42]],
            row_count=1,
            truncated=False,
        )
        formatted = _format_results(result)
        assert "(1 row)" in formatted

    def test_truncated_note(self):
        result = TabularResult(
            columns=["x"],
            rows=[[1]] * 100,
            row_count=500,
            truncated=True,
        )
        formatted = _format_results(result)
        assert "Results truncated to 100 rows out of 500" in formatted

    def test_null_values_rendered_as_empty(self):
        result = TabularResult(
            columns=["x"],
            rows=[[None]],
            row_count=1,
            truncated=False,
        )
        formatted = _format_results(result)
        # None should render as empty string in the table cell
        assert "|  |" in formatted

    def test_empty_columns(self):
        result = TabularResult(columns=[], rows=[], row_count=0, truncated=False)
        assert _format_results(result) == "Query returned no columns."


# ─── format_tabular_evidence ─────────────────────────────────────────────────


class TestFormatTabularEvidence:
    def test_full_evidence(self):
        result = TabularResult(
            columns=["category", "total"],
            rows=[["electronics", 1500]],
            row_count=1,
            truncated=False,
        )
        evidence = format_tabular_evidence(
            question="What is the total revenue by category?",
            sql="SELECT category, SUM(amount) AS total FROM source GROUP BY category",
            result=result,
            document_name="sales.csv",
        )
        assert "**Question:** What is the total revenue by category?" in evidence
        assert "```sql" in evidence
        assert "SELECT category, SUM(amount)" in evidence
        assert "| electronics | 1500 |" in evidence
        assert "*(Source: sales.csv)*" in evidence


# ─── generate_sql ────────────────────────────────────────────────────────────


class TestGenerateSql:
    PROFILE = {
        "row_count": 1000,
        "column_count": 3,
        "columns": [
            {
                "name": "category",
                "type": "VARCHAR",
                "semantic_type": "category",
                "null_count": 0,
                "distinct_count": 5,
            },
            {
                "name": "amount",
                "type": "DOUBLE",
                "semantic_type": "measure",
                "null_count": 10,
                "distinct_count": 950,
            },
            {
                "name": "date",
                "type": "DATE",
                "semantic_type": "datetime",
                "null_count": 0,
                "distinct_count": 365,
            },
        ],
        "measures": ["amount"],
        "dimensions": ["category", "date"],
        "text_columns": [],
    }

    def test_valid_sql_returned(self):
        """When the LLM returns a valid SELECT query, generate_sql returns it."""
        llm_response = json.dumps(
            {
                "sql": "SELECT category, SUM(amount) AS total FROM source GROUP BY category ORDER BY total DESC",
                "explanation": "Groups by category",
            }
        )

        with patch(
            "app.graph.services.tabular_query.json_chat",
            return_value=json.loads(llm_response),
        ):
            sql = generate_sql(self.PROFILE, "total amount by category", "test-model")

        assert sql is not None
        assert "SELECT" in sql.upper()
        assert "GROUP BY" in sql.upper()

    def test_none_when_llm_returns_null_sql(self):
        """When the LLM can't answer from the schema, it returns sql=null and generate_sql returns None."""
        with patch(
            "app.graph.services.tabular_query.json_chat",
            return_value={"sql": None, "explanation": "Can't answer"},
        ):
            sql = generate_sql(self.PROFILE, "what color is the sky", "test-model")
        assert sql is None

    def test_none_when_llm_returns_non_dict(self):
        with patch("app.graph.services.tabular_query.json_chat", return_value="not a dict"):
            sql = generate_sql(self.PROFILE, "some question", "test-model")
        assert sql is None

    def test_none_when_sql_fails_validation(self):
        """When the LLM generates a non-SELECT statement, generate_sql rejects it."""
        with patch(
            "app.graph.services.tabular_query.json_chat",
            return_value={"sql": "DELETE FROM source", "explanation": "oops"},
        ):
            sql = generate_sql(self.PROFILE, "delete everything", "test-model")
        assert sql is None

    def test_none_when_json_chat_fails(self):
        """When json_chat returns its fallback (None), generate_sql returns None."""
        with patch("app.graph.services.tabular_query.json_chat", return_value=None):
            sql = generate_sql(self.PROFILE, "some question", "test-model")
        assert sql is None


# ─── _build_sql_gen_prompt ───────────────────────────────────────────────────


class TestBuildSqlGenPrompt:
    def test_prompt_includes_question_and_schema(self):
        profile = {
            "row_count": 50,
            "column_count": 1,
            "columns": [
                {
                    "name": "x",
                    "type": "INTEGER",
                    "semantic_type": "other",
                    "null_count": 0,
                    "distinct_count": 50,
                }
            ],
        }
        prompt = _build_sql_gen_prompt(profile, "what is the sum of x?")
        assert "Question: what is the sum of x?" in prompt
        assert '"x" INTEGER' in prompt
        assert "Table: source (50 rows, 1 columns)" in prompt

    def test_prompt_instructs_try_cast_for_null_handling(self):
        """The SQL gen system prompt must tell the LLM to use TRY_CAST (not CAST) and to handle
        null-like strings ('Null', 'null', 'N/A', '') in CSV data - without this, a CAST
        on a column containing the literal string 'Null' raises a Conversion Error."""
        from app.graph.services.tabular_query import _SQL_GEN_SYSTEM_PROMPT

        assert "TRY_CAST" in _SQL_GEN_SYSTEM_PROMPT
        assert "Null" in _SQL_GEN_SYSTEM_PROMPT or "null" in _SQL_GEN_SYSTEM_PROMPT
        assert "DOUBLE" in _SQL_GEN_SYSTEM_PROMPT
