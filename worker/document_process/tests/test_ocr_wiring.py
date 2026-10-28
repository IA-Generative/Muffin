"""The OCR pods wired into the extraction: liteparse's options, the fingerprint, the two ways a file is extracted."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import parsing, reuse, task_logging, tasks
from app.config import settings

HASH = "a" * 64


# --- liteparse ---


@pytest.fixture
def lite(monkeypatch):
    """LiteParse, replaced: what it was made with."""
    made = []

    def make(**options):
        parser = MagicMock()
        parser.options = options
        parser.parse.return_value = SimpleNamespace(
            pages=[],
            screenshots=[SimpleNamespace(page_num=4, image_bytes=b"png", width=10, height=20)],
        )
        made.append(parser)
        return parser

    monkeypatch.setattr(parsing, "LiteParse", make)
    # The process's one parser is made on first use: not the one an earlier test made.
    monkeypatch.setattr(parsing, "_parser", None)
    return made


def test_by_default_liteparse_runs_tesseract_itself_as_before(lite, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    parsing.parse_file(b"pdf")
    options = lite[0].options
    assert options["ocr_enabled"] is True and options["include_complexity"] is False
    assert options["ocr_language"] == settings.OCR_LANGUAGE and options["extract_screenshots"] is True


def test_with_the_ocr_pods_liteparse_does_not_run_an_ocr_and_says_which_pages_need_one(lite, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    parsing.parse_file(b"pdf")
    options = lite[0].options
    assert options["ocr_enabled"] is False and options["include_complexity"] is True
    assert options["extract_screenshots"] is True and options["emit_word_boxes"] is True


@pytest.mark.parametrize(
    "numbers, expected",
    [([3], "3"), ([1, 2, 3], "1-3"), ([5, 1, 2, 9, 7, 8], "1-2,5,7-9"), ([2, 2, 3], "2-3"), ([], "")],
)
def test_pages_are_written_the_way_liteparse_reads_them(numbers, expected):
    assert parsing._page_list(numbers) == expected


def test_pages_are_rendered_at_the_ocr_dpi_and_only_those(lite, monkeypatch):
    monkeypatch.setattr(settings, "OCR_PAGE_DPI", 220)
    assert parsing.render_pages(b"pdf", [4, 6, 7]) == {4: (b"png", 10, 20)}
    options = lite[0].options
    assert options["dpi"] == 220 and options["target_pages"] == "4,6-7"
    assert options["ocr_enabled"] is False and options["extract_screenshots"] is True
    assert options["extract_blocks"] is False and options["emit_word_boxes"] is False
    lite[0].close.assert_called_once()


def test_the_fallback_reads_the_given_pages_with_tesseract_even_with_the_ocr_pods(lite, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    parsing.tesseract_pages(b"pdf", [3, 4, 9])
    options = lite[0].options
    assert options["ocr_enabled"] is True and options["target_pages"] == "3-4,9"
    assert options["include_complexity"] is False
    lite[0].close.assert_called_once()


# --- the fingerprint (#300) ---


def _legacy_extraction(content_hash: str) -> str:
    """The fingerprint as it was before the OCR pods: nothing in it may move for a deployment that does not use them."""
    return reuse._digest(
        {
            "version": reuse.FINGERPRINT_VERSION,
            "stage": "extraction",
            "file": content_hash,
            "ocr": settings.OCR_LANGUAGE,
            "parser": reuse._parser_version(),
            "range": settings.PARSE_RANGE_PAGES,
            "layout": 1,
        }
    )


def test_with_the_default_engine_the_fingerprint_is_what_it_was(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    assert reuse.extraction(HASH) == _legacy_extraction(HASH)


def test_a_file_extracted_by_the_ocr_pods_is_not_the_one_tesseract_extracted(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    tesseract = reuse.extraction(HASH)
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    assert reuse.extraction(HASH) != tesseract


@pytest.mark.parametrize(
    "name, value",
    [
        ("OCR_PIPELINE_VERSION", "2"),
        ("OCR_PAGE_DPI", 300),
        ("OCR_SCANNED_MIN_CHARS", 50),
        ("OCR_REGION_MIN_SCORE", 0.7),
        ("OCR_REGION_MIN_PIXELS", 64),
        ("OCR_MAX_REGIONS_PER_PAGE", 50),
        ("OCR_READ_TABLES_AS_TEXT", False),
    ],
)
def test_what_the_pods_reading_depends_on_changes_the_fingerprint(monkeypatch, name, value):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    before = reuse.extraction(HASH)
    monkeypatch.setattr(settings, name, value)
    assert reuse.extraction(HASH) != before


def test_the_pods_settings_do_not_move_the_default_engines_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    before = reuse.extraction(HASH)
    monkeypatch.setattr(settings, "OCR_PIPELINE_VERSION", "99")
    monkeypatch.setattr(settings, "OCR_PAGE_DPI", 400)
    assert reuse.extraction(HASH) == before


def test_every_stage_that_follows_depends_on_the_engine_too(monkeypatch):
    collection = {
        "chunking_strategy": "recursive", "chunk_size": 1000, "chunk_overlap": 100,
        "embedding_model": "m", "instructions": {}, "pipeline_windows": {},
    }  # fmt: skip
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    before = reuse.chunks(HASH, collection)
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    assert reuse.chunks(HASH, collection) != before


# --- the two ways a file is extracted ---

DOCUMENT = {
    "id": "doc-1",
    "type": "file",
    "name": "scan.pdf",
    "storage_key": "docs/scan.pdf",
    "collection_id": "col-1",
}
PDF = b"%PDF-1.4 a scan"


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    storage = MagicMock()
    storage.get_object.return_value = PDF
    monkeypatch.setattr(tasks._shared, "storage", storage)
    backend.get_document.return_value = DOCUMENT
    return backend


def _parsed(*numbers):
    return SimpleNamespace(
        pages=[SimpleNamespace(page_num=n, text=f"p{n}", text_items=[], width=600, height=800) for n in numbers],
        screenshots=[],
    )


def test_a_file_extracted_whole_has_its_scanned_pages_read_by_the_pods(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 2)
    parsed, read = _parsed(1, 2), _parsed(1, 2)
    read.pages[1].text = "read by the pods"
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=parsed))
    ocr = MagicMock(return_value=read)
    monkeypatch.setattr(tasks._shared, "read_scanned_pages", ocr)

    tasks.process_document("doc-1")

    ocr.assert_called_once_with("doc-1", PDF, parsed)
    contents = {call.kwargs["page_number"]: call.kwargs["content"] for call in backend.add_page.call_args_list}
    assert contents == {1: "p1", 2: "read by the pods"}


def test_a_range_of_a_long_pdf_has_its_scanned_pages_read_by_the_pods_too(backend, monkeypatch):
    parsed, read = _parsed(26, 27), _parsed(26, 27)
    read.pages[0].text = "read by the pods"
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=parsed))
    ocr = MagicMock(return_value=read)
    monkeypatch.setattr(tasks._shared, "read_scanned_pages", ocr)
    backend.stage_done.return_value = {"done": 1, "expected": 4, "complete": False, "completed_now": False}
    payload = {
        "document_id": "doc-1", "collection_id": "col-1", "storage_key": "docs/scan.pdf", "size": 2,
        "total": 100, "window": 4, "started": 0, "parent_task_id": "parent-1", "first": 26,
    }  # fmt: skip

    tasks.parse_page_range(payload)

    ocr.assert_called_once_with("doc-1", PDF, parsed)
    contents = {call.kwargs["page_number"]: call.kwargs["content"] for call in backend.add_page.call_args_list}
    assert contents == {26: "read by the pods", 27: "p27"}


def test_a_revoked_range_writes_nothing(backend, monkeypatch):
    from app.task_revocation import TaskRevoked

    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_parsed(1)))
    monkeypatch.setattr(tasks._shared, "read_scanned_pages", MagicMock(side_effect=TaskRevoked()))
    payload = {
        "document_id": "doc-1", "collection_id": "col-1", "storage_key": "docs/scan.pdf", "size": 25,
        "total": 100, "window": 4, "started": 0, "parent_task_id": "parent-1", "first": 1,
    }  # fmt: skip
    with pytest.raises(TaskRevoked):
        tasks.parse_page_range(payload)
    backend.add_page.assert_not_called()
    backend.update_status.assert_not_called()
