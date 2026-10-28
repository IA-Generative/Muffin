"""The formats Muffin accepted before the spreadsheets were read by app/tabular/sheets (TSV, PSV, JSON, JSONL,
Parquet), and what was added to the analysis for them."""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.tabular.sheets.analyzer import analyze_file
from app.tabular.sheets.limits import Limits
from app.tabular.sheets.readers import UnreadableFile, UnsupportedFormat, detect_format
from app.tabular.sheets.tables import write_tables


def _columns(result: dict, sheet: int = 0) -> dict[str, dict]:
    return {column["name"]: column for column in result["sheets"][sheet]["columns"]}


# --- TSV and PSV: a CSV whose delimiter the extension gives ---


@pytest.mark.parametrize(("name", "delimiter"), [("data.tsv", "\t"), ("data.psv", "|")])
def test_a_tsv_or_a_psv_is_read_with_the_delimiter_its_extension_gives(tmp_path, name, delimiter):
    path = tmp_path / name
    path.write_text(
        delimiter.join(["region", "montant"]) + "\n" + delimiter.join(["Nord", "10"]) + "\n", encoding="utf-8"
    )

    result = analyze_file(path, name)

    sheet = result["sheets"][0]
    assert (sheet["name"], sheet["rows"], sheet["header_detected"]) == ("data", 1, True)
    assert list(_columns(result)) == ["region", "montant"]
    assert _columns(result)["montant"]["type"] == "integer"


def test_a_tsv_keeps_a_comma_inside_a_value_instead_of_guessing_it_is_the_delimiter(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("nom\tprix\nstylo, bleu\t1,5\ncahier, A4\t2,5\n", encoding="utf-8")

    result = analyze_file(path, "data.tsv")

    assert list(_columns(result)) == ["nom", "prix"]
    assert _columns(result)["nom"]["type"] == "text"
    assert _columns(result)["prix"]["type"] == "number"  # the decimal comma is understood, not read as a delimiter


# --- Parquet ---


def test_a_parquet_file_declares_its_header_and_keeps_its_types(tmp_path):
    path = tmp_path / "data.parquet"
    pq.write_table(
        pa.table(
            {
                "id": pa.array([1, 2, 3], pa.int64()),
                "prix": pa.array([1.5, 2.5, None], pa.float64()),
                "jour": pa.array([dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]),
                "nom": ["a", "b", "c"],
                "actif": [True, False, True],
            }
        ),
        path,
    )

    result = analyze_file(path, "data.parquet")

    assert result["file"]["format"] == "parquet"
    sheet = result["sheets"][0]
    assert (sheet["rows"], sheet["header_detected"]) == (3, True)
    kinds = {name: column["type"] for name, column in _columns(result).items()}
    assert kinds == {"id": "integer", "prix": "number", "jour": "date", "nom": "text", "actif": "boolean"}
    assert _columns(result)["prix"]["null"] == 1


def test_the_first_row_of_a_parquet_file_is_data_not_a_header(tmp_path):
    """A reader that declares its header does not repeat it in the rows: nothing may be taken for one and dropped."""
    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"a": ["x", "y", "z"], "b": ["u", "v", "w"]}), path)

    result = analyze_file(path, "data.parquet")
    destination = tmp_path / "out"
    destination.mkdir()
    described = write_tables(path, "data.parquet", result, destination)

    assert result["sheets"][0]["rows"] == 3
    assert described[0]["rows"] == 3
    assert pq.read_table(destination / "0.parquet").to_pylist() == [
        {"a": "x", "b": "u"},
        {"a": "y", "b": "v"},
        {"a": "z", "b": "w"},
    ]


def test_a_parquet_file_survives_a_round_trip_through_the_typed_copy(tmp_path):
    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"n": [1, 2, 3], "label": ["a", None, "c"]}), path)
    result = analyze_file(path, "data.parquet")
    destination = tmp_path / "out"
    destination.mkdir()

    described = write_tables(path, "data.parquet", result, destination)

    assert described[0]["columns"] == [{"name": "n", "sql_type": "BIGINT"}, {"name": "label", "sql_type": "VARCHAR"}]
    assert pq.read_table(destination / "0.parquet").to_pylist() == [
        {"n": 1, "label": "a"},
        {"n": 2, "label": None},
        {"n": 3, "label": "c"},
    ]


# --- JSON and JSONL ---


def test_a_json_array_of_objects_is_a_sheet(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps([{"nom": "a", "n": 1}, {"nom": "b", "n": 2}]), encoding="utf-8")

    result = analyze_file(path, "data.json")

    assert (result["file"]["format"], result["sheets"][0]["rows"]) == ("json", 2)
    assert list(_columns(result)) == ["nom", "n"]
    assert _columns(result)["n"]["numeric"]["sum"] == 3


def test_a_jsonl_file_is_one_object_per_line_and_ndjson_is_the_same(tmp_path):
    for name in ("data.jsonl", "data.ndjson"):
        path = tmp_path / name
        path.write_text('{"a": 1, "b": "x"}\n{"a": 2, "b": "y"}\n{"a": 3, "b": "z"}\n', encoding="utf-8")
        result = analyze_file(path, name)
        assert (result["file"]["format"], result["sheets"][0]["rows"]) == ("jsonl", 3)


def test_nested_values_and_decimals_become_text_and_numbers(tmp_path):
    path = tmp_path / "data.parquet"
    pq.write_table(
        pa.table(
            {
                "montant": pa.array([Decimal("10.50"), Decimal("20.25")], pa.decimal128(10, 2)),
                "meta": pa.array([{"k": "v"}, {"k": "w"}]),
                "tags": pa.array([["a", "b"], ["c"]]),
            }
        ),
        path,
    )

    result = analyze_file(path, "data.parquet")

    columns = _columns(result)
    assert columns["montant"]["type"] == "number" and columns["montant"]["numeric"]["max"] == 20.25
    assert columns["meta"]["type"] == "text" and columns["tags"]["type"] == "text"
    assert json.loads(columns["tags"]["sample_values"][0]) == ["a", "b"]


def test_a_broken_parquet_or_json_file_is_refused_with_a_clear_message(tmp_path):
    (tmp_path / "bad.parquet").write_bytes(b"PAR1 but not a parquet file at all")
    (tmp_path / "bad.json").write_text("{this is not json", encoding="utf-8")
    with pytest.raises(UnreadableFile, match="parquet"):
        analyze_file(tmp_path / "bad.parquet", "bad.parquet")
    with pytest.raises(UnreadableFile, match="json"):
        analyze_file(tmp_path / "bad.json", "bad.json")


def test_a_file_that_says_parquet_and_is_not_is_refused_before_it_is_read(tmp_path):
    path = tmp_path / "fake.parquet"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(UnreadableFile, match="not a valid .parquet"):
        detect_format(path, "fake.parquet")


def test_an_unknown_extension_is_refused(tmp_path):
    path = tmp_path / "data.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(UnsupportedFormat, match="expected csv, tsv, psv, json, jsonl, parquet, xlsx, xls, ods"):
        detect_format(path, "data.pdf")


def test_xlsm_is_an_xlsx_and_ndjson_a_jsonl(tmp_path):
    xlsm = tmp_path / "macro.xlsm"
    xlsm.write_bytes(b"PK\x03\x04 not read here")
    assert detect_format(xlsm, "macro.xlsm") == "xlsx"
    jsonl = tmp_path / "a.ndjson"
    jsonl.write_text('{"a": 1}\n', encoding="utf-8")
    assert detect_format(jsonl, "a.ndjson") == "jsonl"


def test_a_json_file_with_only_empty_values_has_no_data(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text('{"a": null}\n{"a": ""}\n', encoding="utf-8")
    result = analyze_file(path, "empty.jsonl")
    assert result["sheets"][0]["rows"] == 0 and "The file contains no data" in result["warnings"]


# --- the average length of a text, as it really is ---


def test_the_average_length_is_the_real_one_even_when_the_text_is_cut_for_the_rest(tmp_path):
    """A long text is cut at max_cell_chars for the counts, but its length is what tells a free text from a label."""
    long = "x" * 1000
    path = tmp_path / "data.csv"
    path.write_text(f"id,libelle,commentaire\n1,a,{long}\n2,bb,{long}\n3,ccc,{long}\n", encoding="utf-8")

    columns = _columns(analyze_file(path, "data.csv", Limits()))

    assert columns["libelle"]["text"]["avg_length"] == 2.0
    assert columns["commentaire"]["text"]["avg_length"] == 1000.0
    assert columns["commentaire"]["text"]["max_length"] == Limits().max_cell_chars  # still cut, as documented


def test_a_column_without_text_has_no_text_profile(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("n\n1\n2\n3\n", encoding="utf-8")
    assert "text" not in _columns(analyze_file(path, "data.csv"))["n"]


def _unused(_: Path) -> None:  # pragma: no cover - keeps the import used when the helpers above change
    return None
