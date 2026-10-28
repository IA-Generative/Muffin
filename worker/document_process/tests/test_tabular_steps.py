"""Tests unitaires pour les étapes du pipeline tabulaire.

Couverture :
- ``validate_document`` : validation MIME + récupération document/settings ;
- ``source_name``, ``downloaded`` : le nom que les lecteurs reconnaissent, le fichier téléchargé (taille vérifiée) ;
- ``analyze`` : l'analyse en flux, un fichier sans donnée refusé ;
- ``write_tables`` : une copie Parquet typée par feuille dans S3, à la place de celles d'avant ;
- ``build_profile`` : le profil du document, tiré de l'analyse ;
- ``persist_profile`` : sauvegarde du profil et des feuilles côté backend ;
- ``write_pages`` : le texte du fichier, une page CSV par feuille ;
- ``generate_summary`` / ``generate_qa_pairs`` : résumé et QA basés sur le profil (prompt tabulaire,
  mais même envoi LLM et même sauvegarde que les documents classiques).

Chaque test mocke ``_shared`` pour isoler la logique métier des appels backend/LLM/storage ; les fichiers, eux, sont
de vrais fichiers.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow.parquet as pq
import pytest
from openpyxl import Workbook

from app.tabular.detect import TabularFormat
from app.tabular.sheets import compat
from app.tabular.sheets.limits import Limits
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


def _workbook(path: Path, sheets: dict[str, list[list]]) -> Path:
    workbook = Workbook(write_only=True)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return path


SALES = [["region", "montant"], ["Nord", 10], ["Sud", 20], ["Nord", 30]]
CLIENTS = [["id", "nom"], [1, "Alice"], [2, "Bob"]]


# ---------------------------------------------------------------------------
# source_name
# ---------------------------------------------------------------------------


class TestSourceName:
    def test_keeps_the_stem_and_takes_the_extension_of_the_recognized_format(self):
        assert steps.source_name({"name": "rapport 2025.XLS"}, TabularFormat.XLS) == "rapport 2025.xls"

    def test_a_file_recognized_by_its_content_gets_the_extension_it_was_recognized_as(self):
        assert steps.source_name({"name": "export"}, TabularFormat.CSV) == "export.csv"
        assert steps.source_name({"name": "data.txt"}, TabularFormat.TSV) == "data.tsv"

    def test_a_name_without_stem_still_has_one(self):
        assert steps.source_name({"name": ""}, TabularFormat.CSV) == "data.csv"


# ---------------------------------------------------------------------------
# downloaded
# ---------------------------------------------------------------------------


class TestDownloaded:
    def test_the_file_is_downloaded_into_a_folder_that_goes_with_the_block(self, mock_shared):
        mock_shared.storage.head_object.return_value = {"ContentLength": 12}
        mock_shared.storage.download_fileobj.side_effect = lambda key, handle: handle.write(b"a,b\n1,2\n")

        with steps.downloaded("docs/x.csv", Limits()) as path:
            assert path.read_bytes() == b"a,b\n1,2\n"
            kept = path
        assert not kept.exists() and not kept.parent.exists()
        mock_shared.storage.download_fileobj.assert_called_once()
        assert mock_shared.storage.download_fileobj.call_args.args[0] == "docs/x.csv"

    def test_the_file_keeps_the_extension_it_is_given_for_the_libraries_that_go_by_it(self, mock_shared):
        mock_shared.storage.head_object.return_value = {"ContentLength": 1}
        mock_shared.storage.download_fileobj.side_effect = lambda key, handle: handle.write(b"x")
        with steps.downloaded("docs/x", Limits(), ".xlsx") as path:
            assert path.suffix == ".xlsx"
        with steps.downloaded("docs/x", Limits()) as path:
            assert path.suffix == ""

    def test_a_file_over_the_limit_is_refused_before_it_is_downloaded(self, mock_shared):
        mock_shared.storage.head_object.return_value = {"ContentLength": 5 * 2**20}
        with pytest.raises(ValueError, match="File too large: 5 MB, the limit is 1 MB"):
            with steps.downloaded("docs/x.csv", Limits(max_file_bytes=2**20)):
                pass
        mock_shared.storage.download_fileobj.assert_not_called()

    def test_the_folder_goes_even_when_the_block_fails(self, mock_shared):
        mock_shared.storage.head_object.return_value = {"ContentLength": 1}
        mock_shared.storage.download_fileobj.side_effect = lambda key, handle: handle.write(b"x")
        seen = []
        with pytest.raises(RuntimeError):
            with steps.downloaded("docs/x.csv", Limits()) as path:
                seen.append(path)
                raise RuntimeError("boom")
        assert not seen[0].parent.exists()


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_analyses_every_sheet_of_a_workbook(self, tmp_path):
        path = _workbook(tmp_path / "f.xlsx", {"Ventes": SALES, "Clients": CLIENTS})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")
        assert [sheet["name"] for sheet in analysis["sheets"]] == ["Ventes", "Clients"]
        assert analysis["summary"]["rows"] == 5

    def test_a_file_with_no_data_is_refused(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="no data"):
            steps.analyze(path, "empty.csv", Limits(), "doc-1")

    def test_a_workbook_of_empty_sheets_is_refused_too(self, tmp_path):
        path = _workbook(tmp_path / "f.xlsx", {"Vide": [], "Aussi": []})
        with pytest.raises(ValueError, match="no data"):
            steps.analyze(path, "f.xlsx", Limits(), "doc-1")


# ---------------------------------------------------------------------------
# write_tables
# ---------------------------------------------------------------------------


class TestWriteTables:
    def _uploaded(self, mock_shared):
        """What was uploaded, by key - read back while the local copies still exist."""
        uploaded: dict[str, bytes] = {}

        def upload(key, handle, content_type="x"):
            uploaded[key] = handle.read()

        mock_shared.storage.upload_fileobj.side_effect = upload
        return uploaded

    def test_one_typed_copy_per_sheet_under_the_documents_folder(self, mock_shared, tmp_path):
        uploaded = self._uploaded(mock_shared)
        path = _workbook(tmp_path / "f.xlsx", {"Ventes": SALES, "Clients": CLIENTS})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")

        described, keys, folder = steps.write_tables(path, "f.xlsx", analysis, "col-1", "doc-1", Limits())

        assert keys == {0: "documents/col-1/doc-1/tables/0.parquet", 1: "documents/col-1/doc-1/tables/1.parquet"}
        assert set(uploaded) == set(keys.values())
        assert described[0]["rows"] == 3 and described[1]["rows"] == 2
        assert described[0]["columns"] == [
            {"name": "region", "sql_type": "VARCHAR"},
            {"name": "montant", "sql_type": "BIGINT"},
        ]
        assert pq.read_table(io.BytesIO(uploaded[keys[0]])).to_pylist()[0] == {"region": "Nord", "montant": 10}
        assert (folder / "0.parquet").is_file()

    def test_what_a_former_extraction_left_goes_first(self, mock_shared, tmp_path):
        """The tables of the folder (a workbook that had more sheets) and the single file of before the sheets."""
        self._uploaded(mock_shared)
        path = _workbook(tmp_path / "f.xlsx", {"Ventes": SALES})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")

        steps.write_tables(path, "f.xlsx", analysis, "col-1", "doc-1", Limits())

        mock_shared.storage.delete_prefix.assert_called_once_with("documents/col-1/doc-1/tables/")
        mock_shared.storage.delete_objects.assert_called_once_with(["documents/col-1/doc-1.parquet"])
        # and only then are the new ones written
        names = [call[0] for call in mock_shared.storage.method_calls]
        assert names.index("delete_prefix") < names.index("upload_fileobj")

    def test_a_sheet_without_rows_has_no_copy(self, mock_shared, tmp_path):
        self._uploaded(mock_shared)
        path = _workbook(tmp_path / "f.xlsx", {"Vide": [], "Ventes": SALES})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")

        described, keys, _ = steps.write_tables(path, "f.xlsx", analysis, "col-1", "doc-1", Limits())

        assert list(described) == [1] and list(keys) == [1]


# ---------------------------------------------------------------------------
# build_profile
# ---------------------------------------------------------------------------


class TestBuildProfile:
    def test_the_profile_is_the_main_sheets_with_the_workbook_around_it(self, tmp_path):
        path = _workbook(tmp_path / "f.xlsx", {"Clients": CLIENTS, "Ventes": SALES})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")

        profile = steps.build_profile(analysis, TabularFormat.XLSX, "doc-1")

        assert (profile.row_count, profile.column_count, profile.format) == (3, 2, "xlsx")
        assert profile.primary_sheet == "Ventes"
        assert [sheet["name"] for sheet in profile.sheets] == ["Clients", "Ventes"]
        assert [column.name for column in profile.columns] == ["region", "montant"]

    def test_a_file_with_no_data_has_no_profile(self):
        with pytest.raises(ValueError, match="no data"):
            compat.profile_from_analysis({"sheets": []}, "csv")


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
        # In place of what an earlier run recorded for this document (#299).
        mock_shared.backend_client.replace_generated_qa.assert_called_once()
        call = mock_shared.backend_client.replace_generated_qa.call_args
        assert call.args[:3] == ("col-1", "doc-1", "tabular")
        (pair,) = call.args[3]
        assert (pair["question"], pair["answer"], pair["embedding"]) == ("How many rows?", "5", [0.3, 0.4])

    def test_tolerates_embedding_failure(self, mock_shared, fake_profile, fake_settings):
        mock_shared._chat.return_value = '[{"question": "Q?", "answer": "A"}]'
        mock_shared.backend_client.embed.side_effect = RuntimeError("LLM hub unavailable")

        result = steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)

        assert len(result) == 1
        mock_shared.backend_client.replace_generated_qa.assert_called_once_with(
            "col-1", "doc-1", "tabular", [{"question": "Q?", "answer": "A", "embedding": None}]
        )

    def test_skips_when_no_model_configured(self, mock_shared, fake_profile, fake_settings):
        mock_shared._model_for.return_value = None

        result = steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)

        assert result == []
        mock_shared._chat.assert_not_called()
        mock_shared.backend_client.replace_generated_qa.assert_not_called()

    def test_raises_on_invalid_json(self, mock_shared, fake_profile, fake_settings):
        mock_shared._chat.return_value = "not json at all"

        with pytest.raises(ValueError):
            steps.generate_qa_pairs(fake_profile, "doc-1", "col-1", fake_settings)


# ---------------------------------------------------------------------------
# persist_profile with the sheets, write_pages
# ---------------------------------------------------------------------------


class TestPersistSheets:
    def test_the_sheets_travel_with_the_profile_and_say_which_shape_they_are(self, mock_shared, fake_profile):
        steps.persist_profile(fake_profile, "doc-1", [{"index": 0, "name": "Ventes"}])

        profile_dict = mock_shared.backend_client.set_tabular_profile.call_args.args[1]
        assert profile_dict["sheets"] == [{"index": 0, "name": "Ventes"}]
        assert profile_dict["analysis_version"] == compat.ANALYSIS_VERSION
        # What the profile of the document says of the workbook is for the prompts: it is not sent.
        assert "primary_sheet" not in profile_dict

    def test_without_sheets_the_profile_is_what_it_always_was(self, mock_shared, fake_profile):
        steps.persist_profile(fake_profile, "doc-1")
        profile_dict = mock_shared.backend_client.set_tabular_profile.call_args.args[1]
        assert "sheets" not in profile_dict and "analysis_version" not in profile_dict


class TestWritePages:
    def _written(self, mock_shared):
        return {
            c.kwargs["page_number"]: c.kwargs["content"] for c in mock_shared.backend_client.add_page.call_args_list
        }

    def test_a_single_sheet_is_a_single_csv_page_as_before(self, mock_shared, tmp_path):
        mock_shared.storage.upload_fileobj.side_effect = lambda *a, **k: None
        path = tmp_path / "ventes.csv"
        path.write_text("region,montant\nNord,10\nSud,20\n", encoding="utf-8")
        analysis = steps.analyze(path, "ventes.csv", Limits(), "doc-1")
        described, _, folder = steps.write_tables(path, "ventes.csv", analysis, "c", "doc-1", Limits())

        count = steps.write_pages(folder, analysis, described, "doc-1", 100)

        assert count == 1
        assert self._written(mock_shared) == {1: "region,montant\r\nNord,10\r\nSud,20\r\n"}
        mock_shared.backend_client.prune_pages.assert_called_once_with("doc-1", keep=1)

    def test_a_workbook_gets_a_page_per_sheet_named_by_it(self, mock_shared, tmp_path):
        mock_shared.storage.upload_fileobj.side_effect = lambda *a, **k: None
        path = _workbook(tmp_path / "f.xlsx", {"Ventes": SALES, "Clients": CLIENTS})
        analysis = steps.analyze(path, "f.xlsx", Limits(), "doc-1")
        described, _, folder = steps.write_tables(path, "f.xlsx", analysis, "c", "doc-1", Limits())

        count = steps.write_pages(folder, analysis, described, "doc-1", 100)

        written = self._written(mock_shared)
        assert count == 2 and set(written) == {1, 2}
        assert written[1].startswith("# Ventes\n") and written[2].startswith("# Clients\n")
        mock_shared.backend_client.prune_pages.assert_called_once_with("doc-1", keep=2)

    def test_a_long_sheet_is_cut_and_says_how_much_is_left(self, mock_shared, tmp_path):
        mock_shared.storage.upload_fileobj.side_effect = lambda *a, **k: None
        path = tmp_path / "long.csv"
        path.write_text("n\n" + "\n".join(str(i) for i in range(50)) + "\n", encoding="utf-8")
        analysis = steps.analyze(path, "long.csv", Limits(), "doc-1")
        described, _, folder = steps.write_tables(path, "long.csv", analysis, "c", "doc-1", Limits())

        steps.write_pages(folder, analysis, described, "doc-1", 10)

        page = self._written(mock_shared)[1]
        assert page.count("\n") == 1 + 10 + 1  # the header, the ten rows, the note
        assert page.rstrip().endswith("# ... 40 more row(s) in this sheet, not repeated in this page")

    def test_a_sheet_the_page_holds_whole_has_no_note(self, mock_shared, tmp_path):
        mock_shared.storage.upload_fileobj.side_effect = lambda *a, **k: None
        path = tmp_path / "short.csv"
        path.write_text("n\n1\n2\n", encoding="utf-8")
        analysis = steps.analyze(path, "short.csv", Limits(), "doc-1")
        described, _, folder = steps.write_tables(path, "short.csv", analysis, "c", "doc-1", Limits())

        steps.write_pages(folder, analysis, described, "doc-1", 2)

        assert "# ..." not in self._written(mock_shared)[1]
