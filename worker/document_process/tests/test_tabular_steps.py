"""Tests unitaires pour les étapes du pipeline tabulaire.

Couverture :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``export_parquet`` : export DuckDB → S3 via httpfs ;
- ``compute_tabular_profile`` : wrapper autour de compute_profile ;
- ``persist_profile`` : sauvegarde du profil côté backend ;
- ``serialize_to_csv_page`` : sérialisation texte pour le chunking.

Le résumé et les QA ne sont **pas** testés ici car ils sont désormais générés
par les tâches classiques (``summarize_document`` et ``generate_qa_window``)
dispatchées par ``chunk_document``.

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
        fake_table.connection.execute.return_value.fetchall.return_value = [
            ("col1,col2\nval1,val2",),
            ("val3,val4",),
        ]

        steps.serialize_to_csv_page(fake_table, "doc-1")

        fake_table.connection.execute.assert_called_once()
        sql = fake_table.connection.execute.call_args.args[0]
        assert "COPY" in sql
        assert "/dev/stdout" in sql
        mock_shared.backend_client.add_page.assert_called_once()
        call = mock_shared.backend_client.add_page.call_args
        assert call.kwargs["page_number"] == 1
        assert "col1,col2" in call.kwargs["content"]
        assert "val3,val4" in call.kwargs["content"]

    def test_skips_empty_rows(self, mock_shared, fake_table):
        fake_table.connection.execute.return_value.fetchall.return_value = [
            ("data1",),
            ("",),
            ("data2",),
        ]

        steps.serialize_to_csv_page(fake_table, "doc-1")

        content = mock_shared.backend_client.add_page.call_args.kwargs["content"]
        assert "data1" in content
        assert "data2" in content
        # La ligne vide ne doit pas ajouter de ligne supplémentaire
        assert content.count("\n") == 1

    def test_handles_empty_table(self, mock_shared, fake_table):
        fake_table.connection.execute.return_value.fetchall.return_value = []

        steps.serialize_to_csv_page(fake_table, "doc-1")

        mock_shared.backend_client.add_page.assert_called_once_with("doc-1", page_number=1, content="")
