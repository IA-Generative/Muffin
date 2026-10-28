"""Which files are tabular, and in which format (app/tabular/detect.py)."""

import pytest

from app.tabular.detect import TabularFormat, detect_by_extension, detect_by_mime, detect_tabular, is_supported_mime


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("data.csv", TabularFormat.CSV),
        ("data.TSV", TabularFormat.TSV),
        ("data.psv", TabularFormat.PSV),
        ("data.parquet", TabularFormat.PARQUET),
        ("data.json", TabularFormat.JSON),
        ("data.jsonl", TabularFormat.JSONL),
        ("data.ndjson", TabularFormat.JSONL),
        ("data.xlsx", TabularFormat.XLSX),
        ("macro.xlsm", TabularFormat.XLSX),
        ("old.xls", TabularFormat.XLS),
        ("open.ods", TabularFormat.ODS),
    ],
)
def test_the_extension_says_the_format(name, expected):
    assert detect_by_extension(name) is expected
    assert detect_tabular(name) is expected


@pytest.mark.parametrize("name", ["report.pdf", "letter.docx", "slides.pptx", "photo.png", "notes.md", "archive"])
def test_a_document_is_not_tabular(name):
    assert detect_tabular(name) is None


def test_an_xls_and_an_ods_are_tabular_now_they_were_read_as_documents_before():
    """.xls and .ods went through the document parser, which gives text; they have a profile and typed copies now."""
    assert detect_tabular("budget.xls") is TabularFormat.XLS
    assert detect_tabular("budget.ods") is TabularFormat.ODS


@pytest.mark.parametrize(
    "mime",
    [
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.apache.parquet",
    ],
)
def test_the_mime_types_of_the_spreadsheets_are_supported(mime):
    assert is_supported_mime(mime)
    assert detect_by_mime(mime) is not None


def test_a_pdf_mime_type_is_not_supported():
    assert not is_supported_mime("application/pdf")
