"""Tests pour le loader tabulaire.

Couvre :
- les fonctions pures (``_s3_url``, ``_load_statement``, ``_duckdb_kwargs``) ;
- le context manager ``load_tabular`` avec des fichiers locaux (on mocke
  ``_configure_s3`` / ``_configure_spatial`` pour éviter d'installer les
  extensions DuckDB à chaque test, et on remplace l'URL S3 par un chemin
  local via ``_s3_url`` patché).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import duckdb
import pytest

from app.tabular import loader
from app.tabular.detect import TabularFormat

# ---------------------------------------------------------------------------
# Fonctions pures
# ---------------------------------------------------------------------------


class TestS3Url:
    def test_builds_s3_url_with_bucket_and_key(self):
        url = loader._s3_url("documents/col1/doc1.csv")
        # AWS_BUCKET par défaut = "muffin-documents"
        assert url == "s3://muffin-documents/documents/col1/doc1.csv"

    def test_preserves_nested_keys(self):
        url = loader._s3_url("documents/col-1/abc-123-report.csv")
        assert url == "s3://muffin-documents/documents/col-1/abc-123-report.csv"


class TestDuckdbKwargs:
    def test_csv_formats_have_header_and_type_inference(self):
        for fmt in (TabularFormat.CSV, TabularFormat.TSV, TabularFormat.PSV):
            kwargs = loader._duckdb_kwargs(fmt)
            assert kwargs == {
                "header": True,
                "ignore_errors": False,
                "all_varchar": False,
            }

    def test_non_csv_formats_return_empty_dict(self):
        for fmt in (
            TabularFormat.PARQUET,
            TabularFormat.JSON,
            TabularFormat.JSONL,
            TabularFormat.XLSX,
        ):
            assert loader._duckdb_kwargs(fmt) == {}


class TestLoadStatement:
    def test_csv_uses_comma_delimiter(self):
        stmt = loader._load_statement(TabularFormat.CSV, "s3://bucket/doc.csv", "t_doc1")
        assert "read_csv_auto('s3://bucket/doc.csv'" in stmt
        assert "delim=','" in stmt
        assert "header=True" in stmt
        assert "CREATE TABLE t_doc1 AS" in stmt

    def test_tsv_uses_tab_delimiter(self):
        stmt = loader._load_statement(TabularFormat.TSV, "s3://bucket/doc.tsv", "t_doc1")
        assert "delim='\\t'" in stmt

    def test_psv_uses_pipe_delimiter(self):
        stmt = loader._load_statement(TabularFormat.PSV, "s3://bucket/doc.psv", "t_doc1")
        assert "delim='|'" in stmt

    def test_parquet_uses_read_parquet(self):
        stmt = loader._load_statement(TabularFormat.PARQUET, "s3://bucket/doc.parquet", "t_doc1")
        assert "read_parquet('s3://bucket/doc.parquet')" in stmt

    def test_json_uses_read_json_auto(self):
        stmt = loader._load_statement(TabularFormat.JSON, "s3://bucket/doc.json", "t_doc1")
        assert "read_json_auto('s3://bucket/doc.json'" in stmt

    def test_jsonl_uses_read_json_auto(self):
        stmt = loader._load_statement(TabularFormat.JSONL, "s3://bucket/doc.jsonl", "t_doc1")
        assert "read_json_auto('s3://bucket/doc.jsonl'" in stmt

    def test_xlsx_uses_st_read_with_layer_0(self):
        stmt = loader._load_statement(TabularFormat.XLSX, "s3://bucket/doc.xlsx", "t_doc1")
        assert "st_read('s3://bucket/doc.xlsx', layer=0)" in stmt

    def test_table_name_is_injected(self):
        stmt = loader._load_statement(TabularFormat.CSV, "s3://bucket/doc.csv", "t_abc_123")
        assert "CREATE TABLE t_abc_123 AS" in stmt

    def test_unsupported_format_raises_value_error(self):
        # On crée un faux format qui n'est pas dans les branches.
        class FakeFormat:
            pass

        with pytest.raises(ValueError, match="Unsupported tabular format"):
            loader._load_statement(FakeFormat(), "s3://bucket/doc", "t_doc1")


# ---------------------------------------------------------------------------
# load_tabular (context manager)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    """Crée un CSV temporaire avec en-tête et 3 lignes."""
    path = tmp_path / "source.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "age", "city"])
        writer.writerow(["Alice", "30", "Paris"])
        writer.writerow(["Bob", "25", "Lyon"])
        writer.writerow(["Charlie", "35", "Marseille"])
    return path


@pytest.fixture
def tmp_json(tmp_path: Path) -> Path:
    """Crée un JSON temporaire (tableau d'objets)."""
    path = tmp_path / "source.json"
    data = [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """Crée un JSONL temporaire (un objet par ligne)."""
    path = tmp_path / "source.jsonl"
    lines = [
        json.dumps({"name": "Alice", "age": 30}),
        json.dumps({"name": "Bob", "age": 25}),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def tmp_parquet(tmp_path: Path) -> Path:
    """Crée un Parquet temporaire via DuckDB."""
    csv_path = tmp_path / "source.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "age"])
        writer.writerow(["Alice", "30"])
        writer.writerow(["Bob", "25"])

    parquet_path = tmp_path / "source.parquet"
    conn = duckdb.connect()
    conn.execute(f"COPY (SELECT * FROM read_csv_auto('{csv_path}', header=True)) TO '{parquet_path}' (FORMAT PARQUET)")
    conn.close()
    return parquet_path


def _patch_s3_and_load(monkeypatch, local_path: Path):
    """Patche ``_s3_url`` pour pointer vers un fichier local, et patche
    ``_configure_s3`` / ``_configure_spatial`` pour ne pas installer les
    extensions DuckDB (inutiles en lecture locale)."""
    monkeypatch.setattr(loader, "_s3_url", lambda _key: str(local_path))
    monkeypatch.setattr(loader, "_configure_s3", lambda _conn: None)
    monkeypatch.setattr(loader, "_configure_spatial", lambda _conn: None)


class TestLoadTabular:
    def test_loads_csv_and_exposes_table_with_document_id_name(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)

        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-123") as table:
            assert table.format == TabularFormat.CSV
            assert table.table_name == "t_doc_123"

            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 3
            assert rows[0][0] == "Alice"
            assert rows[1][0] == "Bob"
            assert rows[2][0] == "Charlie"

    def test_loads_tsv_with_tab_delimiter(self, monkeypatch, tmp_path):
        path = tmp_path / "source.tsv"
        with path.open("w", newline="", encoding="utf-8") as f:
            f.write("name\tage\nAlice\t30\nBob\t25\n")
        _patch_s3_and_load(monkeypatch, path)

        with loader.load_tabular("docs/doc.tsv", TabularFormat.TSV, "doc-tsv") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 2
            # DuckDB infère les types : age devient INTEGER.
            assert rows[0] == ("Alice", 30)

    def test_loads_psv_with_pipe_delimiter(self, monkeypatch, tmp_path):
        path = tmp_path / "source.psv"
        with path.open("w", newline="", encoding="utf-8") as f:
            f.write("name|age\nAlice|30\nBob|25\n")
        _patch_s3_and_load(monkeypatch, path)

        with loader.load_tabular("docs/doc.psv", TabularFormat.PSV, "doc-psv") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 2
            # DuckDB infère les types : age devient INTEGER.
            assert rows[0] == ("Alice", 30)

    def test_loads_json_array(self, monkeypatch, tmp_json):
        _patch_s3_and_load(monkeypatch, tmp_json)

        with loader.load_tabular("docs/doc.json", TabularFormat.JSON, "doc-json") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "Alice"

    def test_loads_jsonl_one_object_per_line(self, monkeypatch, tmp_jsonl):
        _patch_s3_and_load(monkeypatch, tmp_jsonl)

        with loader.load_tabular("docs/doc.jsonl", TabularFormat.JSONL, "doc-jsonl") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "Alice"

    def test_loads_parquet(self, monkeypatch, tmp_parquet):
        _patch_s3_and_load(monkeypatch, tmp_parquet)

        with loader.load_tabular("docs/doc.parquet", TabularFormat.PARQUET, "doc-parquet") as table:
            rows = table.connection.execute(f"SELECT * FROM {table.table_name} ORDER BY name").fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "Alice"

    def test_table_name_replaces_hyphens_with_underscores(self, monkeypatch, tmp_csv):
        """Un UUID contient des tirets ; l'identifiant SQL ne peut pas."""
        _patch_s3_and_load(monkeypatch, tmp_csv)

        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "550e8400-e29b-41d4-a716-446655440000") as table:
            assert table.table_name == "t_550e8400_e29b_41d4_a716_446655440000"
            # La table est utilisable.
            count = table.connection.execute(f"SELECT COUNT(*) FROM {table.table_name}").fetchone()
            assert count[0] == 3

    def test_connection_is_closed_after_context_exit(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)

        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-1") as table:
            pass

        # La connexion est fermée : toute requête doit lever une exception.
        with pytest.raises(duckdb.ConnectionException):
            table.connection.execute("SELECT 1")

    def test_connection_is_closed_even_on_error(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)

        with pytest.raises(RuntimeError, match="boom"):
            with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-1") as table:
                raise RuntimeError("boom")

        with pytest.raises(duckdb.ConnectionException):
            table.connection.execute("SELECT 1")

    def test_load_tabular_calls_configure_s3(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)
        call_count = 0

        def _spy(_conn):
            nonlocal call_count
            call_count += 1

        monkeypatch.setattr(loader, "_configure_s3", _spy)

        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-1"):
            pass

        assert call_count == 1

    def test_load_tabular_calls_configure_spatial_only_for_xlsx(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)
        spatial_calls = 0

        def _spy_spatial(_conn):
            nonlocal spatial_calls
            spatial_calls += 1

        monkeypatch.setattr(loader, "_configure_spatial", _spy_spatial)

        # CSV : spatial ne doit pas être appelé.
        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-1"):
            pass
        assert spatial_calls == 0

    def test_load_tabular_sets_memory_limit_and_threads(self, monkeypatch, tmp_csv):
        _patch_s3_and_load(monkeypatch, tmp_csv)

        with loader.load_tabular("docs/doc.csv", TabularFormat.CSV, "doc-1") as table:
            # DuckDB expose les PRAGMA via duckdb_settings().
            settings_rows = table.connection.execute(
                "SELECT name, value FROM duckdb_settings() WHERE name IN ('memory_limit', 'threads')"
            ).fetchall()
            settings_dict = {row[0]: row[1] for row in settings_rows}

        assert "memory_limit" in settings_dict
        # DuckDB normalise vers des unités binaires (ex: "2GB" -> "1.8 GiB").
        assert "GiB" in str(settings_dict["memory_limit"])
        assert settings_dict["threads"] == str(loader.DUCKDB_THREADS)


# ---------------------------------------------------------------------------
# _configure_s3 / _configure_spatial (intégration légère avec DuckDB)
# ---------------------------------------------------------------------------


class TestConfigureS3:
    def test_sets_s3_credentials_and_endpoint(self):
        # On ne peut pas patcher ``execute`` sur un objet DuckDB (C extension
        # en lecture seule). On utilise un mock de connexion à la place.
        from unittest.mock import MagicMock

        # LOAD suffit et ne lève pas (extension déjà installée, cas nominal en
        # prod comme dans ce mock) - voir _ensure_extension. INSTALL n'est
        # appelé qu'en repli, testé séparément ci-dessous.
        conn = MagicMock()
        loader._configure_s3(conn)

        executed_sql = [call.args[0] for call in conn.execute.call_args_list]
        assert "INSTALL httpfs" not in executed_sql
        assert "LOAD httpfs" in executed_sql
        assert any("SET s3_access_key_id=" in sql for sql in executed_sql)
        assert any("SET s3_secret_access_key=" in sql for sql in executed_sql)
        assert any("SET s3_endpoint=" in sql for sql in executed_sql)
        assert any("SET s3_url_style='path'" in sql for sql in executed_sql)

    def test_installs_extension_when_load_fails(self):
        # En dev, l'extension n'est pas pré-installée dans l'image : LOAD
        # lève duckdb.IOException, ce qui doit déclencher un repli sur
        # INSTALL puis un nouveau LOAD (voir _ensure_extension).
        from unittest.mock import MagicMock

        conn = MagicMock()

        def execute_side_effect(sql, *args, **kwargs):
            if sql == "LOAD httpfs":
                execute_side_effect.calls += 1
                if execute_side_effect.calls == 1:
                    raise duckdb.IOException("extension not found")
            return MagicMock()

        execute_side_effect.calls = 0
        conn.execute.side_effect = execute_side_effect

        loader._configure_s3(conn)

        executed_sql = [call.args[0] for call in conn.execute.call_args_list]
        assert executed_sql.count("LOAD httpfs") == 2
        assert "INSTALL httpfs" in executed_sql
        assert executed_sql.index("INSTALL httpfs") > executed_sql.index("LOAD httpfs")

    def test_strips_http_scheme_from_endpoint(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        loader._configure_s3(conn)

        endpoint_calls = [call.args[0] for call in conn.execute.call_args_list if "s3_endpoint" in str(call.args[0])]
        assert len(endpoint_calls) == 1
        # AWS_ENDPOINT_URL par défaut = "http://localhost:9000"
        assert "localhost:9000" in endpoint_calls[0]
        assert "http://" not in endpoint_calls[0].split("=")[1]


class TestConfigureSpatial:
    def test_loads_spatial(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        loader._configure_spatial(conn)

        executed_sql = [call.args[0] for call in conn.execute.call_args_list]
        assert "INSTALL spatial" not in executed_sql
        assert "LOAD spatial" in executed_sql

    def test_installs_spatial_when_load_fails(self):
        from unittest.mock import MagicMock

        conn = MagicMock()

        def execute_side_effect(sql, *args, **kwargs):
            if sql == "LOAD spatial":
                execute_side_effect.calls += 1
                if execute_side_effect.calls == 1:
                    raise duckdb.IOException("extension not found")
            return MagicMock()

        execute_side_effect.calls = 0
        conn.execute.side_effect = execute_side_effect

        loader._configure_spatial(conn)

        executed_sql = [call.args[0] for call in conn.execute.call_args_list]
        assert executed_sql.count("LOAD spatial") == 2
        assert "INSTALL spatial" in executed_sql
        assert executed_sql.index("INSTALL spatial") > executed_sql.index("LOAD spatial")
