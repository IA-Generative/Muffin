"""Tests unitaires pour les étapes du pipeline tabulaire.

Couverture :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``export_parquet`` : export DuckDB → S3 via httpfs ;
- ``compute_tabular_profile`` : wrapper autour de compute_profile ;
- ``persist_profile`` : sauvegarde du profil côté backend ;
- ``serialize_to_csv_page`` : sérialisation texte pour le chunking ;
- ``generate_summary`` : résumé LLM basé sur le profil (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques) ;
- ``generate_qa_pairs`` : paires QA ancrées dans les stats (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques).

Chaque test mocke ``_shared`` pour isoler la logique métier des appels
backend/LLM/storage.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.tabular.detect import TabularFormat
from app.tabular.loader import LoadedTable
from app.tabular.stats import TabularProfile
from app.tasks import _tabular_steps as steps

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_shared(monkeypatch):
    """Mock toutes les dépendances externes de _shared."""
    monkeypatch.setattr(steps._shared, "backend_client", MagicMock())
    monkeypatch.setattr(steps._shared, "storage", MagicMock())
    monkeypatch.setattr(steps._shared, "_chat", MagicMock(return_value="LLM response"))
    monkeypatch.setattr(steps._shared, "_model_for", MagicMock(return_value="gpt-4o"))
    monkeypatch.setattr(
        steps._shared,
        "_windows",
        MagicMock(return_value={"qa_questions_per_window": 3}),
    )
    return steps._shared


@pytest.fixture
def fake_document():
    return {
        "id": "doc-1",
        "name": "sales.csv",
        "storage_key": "docs/sales.csv",
        "mime_type": "text/csv",
        "collection_id": "col-1",
    }


@pytest.fixture
def fake_settings():
    return {
        "embedding_model": "text-embedding-3-small",
        "instructions": {"summary": "Summarize this", "qa": "Generate QA"},
    }


@pytest.fixture
def fake_profile():
    return TabularProfile(
        row_count=5,
        column_count=3,
        columns=[],
        sample_rows=[],
        format="csv",
        measures=["price"],
        dimensions=["product"],
        text_columns=[],
    )


@pytest.fixture
def fake_table():
    return LoadedTable(connection=MagicMock(), format=TabularFormat.CSV, table_name="t_doc1")


# ---------------------------------------------------------------------------
# validate_document
# ---------------------------------------------------------------------------


class TestValidateDocument:
    def test_returns_document_settings_and_format(self, mock_shared, fake_document, fake_settings):
        mock_shared.backend_client.get_document.return_value = fake_document
        mock_shared.backend_client.get_collection_settings.return_value = fake_settings

        document, settings, fmt = steps.validate_document("doc-1", "col-1", "csv")

        assert document == fake_document
        assert settings == fake_settings
        assert fmt == TabularFormat.CSV

    def test_raises_on_unsupported_mime(self, mock_shared, fake_document, fake_settings):
        fake_document["mime_type"] = "application/x-unknown"
        mock_shared.backend_client.get_document.return_value = fake_document
        mock_shared.backend_client.get_collection_settings.return_value = fake_settings

        with pytest.raises(ValueError, match="Unsupported MIME type"):
            steps.validate_document("doc-1", "col-1", "csv")

    def test_accepts_empty_mime_type(self, mock_shared, fake_document, fake_settings):
        fake_document["mime_type"] = ""
        mock_shared.backend_client.get_document.return_value = fake_document
        mock_shared.backend_client.get_collection_settings.return_value = fake_settings

        document, _, fmt = steps.validate_document("doc-1", "col-1", "csv")
        assert document == fake_document
        assert fmt == TabularFormat.CSV


# ---------------------------------------------------------------------------
# export_parquet
# ---------------------------------------------------------------------------


class TestExportParquet:
    def test_executes_copy_to_s3(self, mock_shared, fake_table):
        mock_shared.storage._bucket = "muffin-docs"

        parquet_key = steps.export_parquet(fake_table, "col-1", "doc-1")

        assert parquet_key == "documents/col-1/doc-1.parquet"
        fake_table.connection.execute.assert_called_once()
        sql = fake_table.connection.execute.call_args.args[0]
        assert "COPY" in sql
        assert "s3://muffin-docs/documents/col-1/doc-1.parquet" in sql
        assert "FORMAT PARQUET" in sql


# ---------------------------------------------------------------------------
# compute_tabular_profile
# ---------------------------------------------------------------------------


class TestComputeTabularProfile:
    def test_calls_compute_profile_and_logs(self, mock_shared, fake_table, monkeypatch):
        expected_profile = TabularProfile(row_count=10, column_count=2, columns=[], sample_rows=[], format="csv")
        monkeypatch.setattr(steps, "compute_profile", lambda table: expected_profile)

        result = steps.compute_tabular_profile(fake_table, "doc-1")

        assert result is expected_profile


# ---------------------------------------------------------------------------
# persist_profile
# ---------------------------------------------------------------------------


class TestPersistProfile:
    def test_persists_profile_with_document_id(self, mock_shared, fake_profile):
        steps.persist_profile(fake_profile, "doc-1")

        mock_shared.backend_client.set_tabular_profile.assert_called_once()
        call_args = mock_shared.backend_client.set_tabular_profile.call_args
        assert call_args.args[0] == "doc-1"
        profile_dict = call_args.args[1]
        assert profile_dict["document_id"] == "doc-1"
        assert profile_dict["row_count"] == 5
        assert profile_dict["format"] == "csv"

    def test_does_not_include_summary_or_questions(self, mock_shared, fake_profile):
        """Le résumé et les QA sont gérés par les tâches classiques, pas
        par le profil tabulaire."""
        steps.persist_profile(fake_profile, "doc-1")

        profile_dict = mock_shared.backend_client.set_tabular_profile.call_args.args[1]
        assert "summary" not in profile_dict
        assert "suggested_questions" not in profile_dict


# ---------------------------------------------------------------------------
# serialize_to_csv_page
# ---------------------------------------------------------------------------


class TestSerializeToCsvPage:
    def test_writes_csv_as_single_page(self, mock_shared, fake_table):
        fake_table.connection.description = [("col1",), ("col2",)]
        fake_table.connection.execute.return_value.fetchall.return_value = [
            ("val1", "val2"),
            ("val3", "val4"),
        ]

        steps.serialize_to_csv_page(fake_table, "doc-1")

        fake_table.connection.execute.assert_called_once()
        sql = fake_table.connection.execute.call_args.args[0]
        assert "SELECT * FROM" in sql
        mock_shared.backend_client.add_page.assert_called_once()
        call = mock_shared.backend_client.add_page.call_args
        assert call.kwargs["page_number"] == 1
        assert "col1,col2" in call.kwargs["content"]
        assert "val3,val4" in call.kwargs["content"]

    def test_handles_non_string_values(self, mock_shared, fake_table):
        """Les entiers et autres types non-string doivent être sérialisés."""
        fake_table.connection.description = [("id",), ("price",)]
        fake_table.connection.execute.return_value.fetchall.return_value = [
            (1, 100),
            (2, 200),
        ]

        steps.serialize_to_csv_page(fake_table, "doc-1")

        content = mock_shared.backend_client.add_page.call_args.kwargs["content"]
        assert "id,price" in content
        assert "1,100" in content
        assert "2,200" in content

    def test_handles_empty_table(self, mock_shared, fake_table):
        fake_table.connection.description = [("col1",), ("col2",)]
        fake_table.connection.execute.return_value.fetchall.return_value = []

        steps.serialize_to_csv_page(fake_table, "doc-1")

        mock_shared.backend_client.add_page.assert_called_once()
        call = mock_shared.backend_client.add_page.call_args
        assert call.kwargs["page_number"] == 1
        # Header only, no data rows
        assert call.kwargs["content"].strip() == "col1,col2"


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    def test_sends_tabular_prompt_and_saves_summary(self, mock_shared, fake_profile, fake_settings):
        mock_shared.backend_client.embed.return_value = [0.1, 0.2]
        mock_shared._chat.return_value = "This dataset contains sales data."

        result = steps.generate_summary(fake_profile, "doc-1", "col-1", fake_settings)

        assert result == "This dataset contains sales data."
        # Same LLM call mechanism as classic summarize_document
        mock_shared._chat.assert_called_once()
        args = mock_shared._chat.call_args.args
        assert args[0] == "gpt-4o"  # model
        assert "analyste de données" in args[1]  # system prompt (tabular)
        assert "csv" in args[2]  # user content includes format
        # Same persistence as classic summarize_document
        mock_shared.backend_client.set_document_summary.assert_called_once()
        call = mock_shared.backend_client.set_document_summary.call_args
        assert call.args[0] == "doc-1"
        assert call.args[1] == "This dataset contains sales data."
        assert call.args[2] == [0.1, 0.2]  # embedding

    def test_tolerates_embedding_failure(self, mock_shared, fake_profile, fake_settings):
        mock_shared.backend_client.embed.side_effect = RuntimeError("LLM hub unavailable")
        mock_shared._chat.return_value = "Summary text."

        result = steps.generate_summary(fake_profile, "doc-1", "col-1", fake_settings)

        assert result == "Summary text."
        mock_shared.backend_client.set_document_summary.assert_called_once_with("doc-1", "Summary text.", None)

    def test_skips_when_no_model_configured(self, mock_shared, fake_profile, fake_settings):
        mock_shared._model_for.return_value = None

        result = steps.generate_summary(fake_profile, "doc-1", "col-1", fake_settings)

        assert result == ""
        mock_shared._chat.assert_not_called()
        mock_shared.backend_client.set_document_summary.assert_not_called()


# ---------------------------------------------------------------------------
# generate_qa_pairs
# ---------------------------------------------------------------------------


class TestGenerateQaPairs:
    def test_sends_tabular_prompt_and_saves_qa_pairs(self, mock_shared, fake_profile, fake_settings):
        mock_shared._chat.return_value = '[{"question": "How many rows?", "answer": "5"}]'
        mock_shared.backend_client.embed.return_value = [0.3, 0.4]

        result = steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)

        assert len(result) == 1
        assert result[0]["question"] == "How many rows?"
        assert result[0]["answer"] == "5"
        # Same LLM call mechanism as classic generate_qa_window
        mock_shared._chat.assert_called_once()
        args = mock_shared._chat.call_args.args
        assert args[0] == "gpt-4o"  # model
        assert "3" in args[1]  # k=3 in system prompt
        # Same persistence as classic generate_qa_window
        mock_shared.backend_client.create_qa_pair.assert_called_once()
        call = mock_shared.backend_client.create_qa_pair.call_args
        assert call.args[0] == "col-1"
        assert call.args[1] == "doc-1"
        assert call.args[2] == "How many rows?"
        assert call.args[3] == "5"
        assert call.args[4] == [0.3, 0.4]  # embedding

    def test_tolerates_embedding_failure(self, mock_shared, fake_profile, fake_settings):
        mock_shared._chat.return_value = '[{"question": "Q?", "answer": "A"}]'
        mock_shared.backend_client.embed.side_effect = RuntimeError("LLM hub unavailable")

        result = steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)

        assert len(result) == 1
        mock_shared.backend_client.create_qa_pair.assert_called_once_with("col-1", "doc-1", "Q?", "A", None)

    def test_skips_when_no_model_configured(self, mock_shared, fake_profile, fake_settings):
        mock_shared._model_for.return_value = None

        result = steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)

        assert result == []
        mock_shared._chat.assert_not_called()
        mock_shared.backend_client.create_qa_pair.assert_not_called()

    def test_raises_on_invalid_json(self, mock_shared, fake_profile, fake_settings):
        mock_shared._chat.return_value = "not json at all"

        with pytest.raises(ValueError):
            steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)
