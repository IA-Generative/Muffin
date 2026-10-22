"""A long PDF is extracted in ranges of pages, a window of them at a time (#331)."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from loguru import logger

from app import parsing, reuse, task_logging, tasks
from app.config import settings

PDF = b"%PDF-1.4 a long one"
DOCUMENT = {
    "id": "doc-1",
    "type": "file",
    "name": "rapport.pdf",
    "storage_key": "docs/rapport.pdf",
    "collection_id": "col-1",
}


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    storage = MagicMock()
    storage.get_object.return_value = PDF
    monkeypatch.setattr(tasks._shared, "storage", storage)
    monkeypatch.setattr(settings, "PARSE_RANGE_PAGES", 25)
    monkeypatch.setattr(settings, "PARSE_WINDOW", 4)
    backend.get_document.return_value = DOCUMENT
    return backend


def _spawned(kind: str) -> list:
    return [call.args for call in tasks._shared._spawn.call_args_list if call.args[2] == f"app.tasks.{kind}"]


def _payload(first: int, total: int = 100, **override) -> dict:
    return {
        "document_id": "doc-1",
        "collection_id": "col-1",
        "storage_key": "docs/rapport.pdf",
        "size": 25,
        "total": total,
        "window": 4,
        "started": time.time() - 60,
        "parent_task_id": "parent-1",
        "first": first,
        **override,
    }


def _pages(first: int, last: int):
    return SimpleNamespace(
        pages=[SimpleNamespace(page_num=n, text=f"p{n}") for n in range(first, last + 1)], screenshots=[]
    )


def test_a_long_pdf_announces_its_ranges_and_starts_a_window_of_them(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 240)

    tasks.process_document("doc-1")

    announced = [call for call in backend.begin_stage.call_args_list if call.args[3]]
    assert announced[0].args[3] == [f"pages:{first}-{first + 24}" for first in range(1, 226, 25)] + ["pages:226-240"]
    starts = [args[1][0]["first"] for args in _spawned("parse_page_range")]
    assert starts == [1, 26, 51, 76]
    payload = _spawned("parse_page_range")[0][1][0]
    assert (payload["total"], payload["size"], payload["window"]) == (240, 25, 4)
    # Neither the chunking nor the end of the extraction until the last range is done.
    assert _spawned("chunk_document") == []
    assert call_progress(backend, 50) == []


def call_progress(backend, progress: int) -> list:
    return [call for call in backend.update_status.call_args_list if call.kwargs.get("progress") == progress]


def test_a_pdf_no_longer_than_a_range_is_extracted_whole(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 25)
    parse = MagicMock(return_value=_pages(1, 25))
    monkeypatch.setattr(tasks._shared, "parse_file", parse)

    tasks.process_document("doc-1")

    parse.assert_called_once_with(PDF)
    assert _spawned("parse_page_range") == []
    assert len(_spawned("chunk_document")) == 1


def test_what_is_not_a_pdf_is_extracted_whole_without_counting_pages(backend, monkeypatch):
    count = MagicMock()
    monkeypatch.setattr(tasks._shared, "count_pages", count)
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=_pages(1, 1)))
    tasks._shared.storage.get_object.return_value = b"PK\x03\x04 a docx"
    backend.get_document.return_value = {**DOCUMENT, "name": "rapport.docx"}

    tasks.process_document("doc-1")

    count.assert_not_called()
    assert len(_spawned("chunk_document")) == 1


def test_a_range_is_parsed_written_and_marked_done_then_starts_the_next_of_the_window(backend, monkeypatch):
    parse = MagicMock(return_value=_pages(26, 50))
    monkeypatch.setattr(tasks._shared, "parse_pages", parse)
    backend.stage_done.return_value = {"done": 2, "expected": 4, "complete": False, "completed_now": False}
    lines = []
    sink = logger.add(lines.append, format="{message}")
    try:
        tasks.parse_page_range(_payload(26, total=100, window=2))
    finally:
        logger.remove(sink)

    parse.assert_called_once_with(PDF, 26, 50)
    assert backend.add_page.call_count == 25
    backend.stage_done.assert_called_once_with("doc-1", "extraction", "pages:26-50")
    backend.update_status.assert_any_call("doc-1", status="indexing", progress=25)
    # The window is 2: this range is followed by the one two ranges after it.
    assert [args[1][0]["first"] for args in _spawned("parse_page_range")] == [76]
    assert _spawned("parse_page_range")[0][4] == "parent-1"
    assert _spawned("chunk_document") == []
    progress = next(line for line in lines if line.startswith("Extracted 2/4"))
    assert "of 100 page(s)" in progress and "left" in progress


def test_the_last_ranges_start_no_further_one(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_pages(76, 100)))
    backend.stage_done.return_value = {"done": 2, "expected": 4, "complete": False, "completed_now": False}

    tasks.parse_page_range(_payload(76))

    assert _spawned("parse_page_range") == []


def test_the_range_that_completes_the_extraction_starts_the_chunking(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_pages(76, 100)))
    backend.stage_done.return_value = {"done": 4, "expected": 4, "complete": True, "completed_now": True}
    lines = []
    sink = logger.add(lines.append, format="{message}")
    try:
        tasks.parse_page_range(_payload(76))
    finally:
        logger.remove(sink)

    backend.prune_pages.assert_called_once_with("doc-1", keep=100)
    backend.update_status.assert_any_call("doc-1", status="indexing", progress=50)
    (chunking,) = _spawned("chunk_document")
    assert chunking[1] == ["doc-1", "col-1"] and chunking[4] == "parent-1"
    assert any(line.startswith("Extracted 4/4") and "left" not in line for line in lines)


def test_a_range_run_again_after_the_extraction_completed_does_not_start_the_chunking_twice(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_pages(76, 100)))
    backend.stage_done.return_value = {"done": 4, "expected": 4, "complete": True, "completed_now": False}

    tasks.parse_page_range(_payload(76))

    assert _spawned("chunk_document") == []
    backend.prune_pages.assert_not_called()


def test_a_range_that_fails_fails_the_document_and_starts_nothing(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(side_effect=RuntimeError("OCR failed")))

    with pytest.raises(RuntimeError):
        tasks.parse_page_range(_payload(26))

    backend.update_status.assert_any_call("doc-1", status="error")
    backend.set_document_error.assert_called_once_with("doc-1", "OCR failed")
    assert _spawned("parse_page_range") == [] and _spawned("chunk_document") == []


def test_a_range_of_an_extraction_that_announced_no_ranges_fails(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_pages(26, 50)))
    backend.stage_done.return_value = {"done": 0, "expected": 0, "complete": False, "completed_now": False}

    with pytest.raises(RuntimeError, match="not announced"):
        tasks.parse_page_range(_payload(26))

    assert _spawned("parse_page_range") == []


def test_the_size_of_the_ranges_is_part_of_the_extraction_s_fingerprint(monkeypatch):
    before = reuse.extraction("f" * 64)
    monkeypatch.setattr(settings, "PARSE_RANGE_PAGES", 50)

    assert reuse.extraction("f" * 64) != before


def _pdf(pages: int) -> bytes:
    kids = " ".join(f"{4 + 2 * page} 0 R" for page in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page in range(pages):
        content = f"BT /F1 18 Tf 20 100 Td (Page {page + 1}) Tj ET".encode()
        objects += [
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {5 + 2 * page} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>".encode(),
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        ]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return body + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_with_the_real_parser_the_pages_are_counted_and_a_range_keeps_its_page_numbers():
    pdf = _pdf(5)

    assert parsing.count_pages(pdf) == 5
    result = parsing.parse_pages(pdf, 2, 3)

    assert [(page.page_num, page.text.strip()) for page in result.pages] == [(2, "Page 2"), (3, "Page 3")]
    assert sorted(screenshot.page_num for screenshot in result.screenshots) == [2, 3]


# -- the window of a ZIP import (#335) ----------------------------------------------------------


def test_the_end_of_the_extraction_frees_the_place_of_the_document_in_its_import(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=_pages(1, 1)))
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 1)

    tasks.process_document("doc-1")

    backend.extraction_done.assert_called_once_with("doc-1")
    assert len(_spawned("chunk_document")) == 1


def test_a_long_pdf_frees_its_place_only_when_its_last_range_completes_the_extraction(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 240)
    tasks.process_document("doc-1")
    backend.extraction_done.assert_not_called()

    monkeypatch.setattr(tasks._shared, "parse_pages", MagicMock(return_value=_pages(226, 240)))
    backend.stage_done.return_value = {"done": 10, "expected": 10, "complete": True, "completed_now": True}
    tasks.parse_page_range(_payload(226, total=240))

    backend.extraction_done.assert_called_once_with("doc-1")


def test_a_backend_that_does_not_answer_never_fails_the_extraction(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=_pages(1, 1)))
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 1)
    backend.extraction_done.side_effect = RuntimeError("backend down")

    tasks.process_document("doc-1")

    assert len(_spawned("chunk_document")) == 1


def test_the_beat_sweeps_the_windows_of_the_imports(backend):
    backend.release_import_queue.return_value = 3

    assert tasks.release_import_queue() == 3
    entry = tasks.celery_app.conf.beat_schedule["release-import-queue"]
    assert entry["task"] == "app.tasks.release_import_queue"
