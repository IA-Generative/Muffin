from types import SimpleNamespace
from unittest.mock import MagicMock

from app import tasks


def _fake_block(text: str, kind: str = "paragraph", bbox=(1.0, 2.0, 100.0, 20.0)):
    x, y, width, height = bbox
    return SimpleNamespace(text=text, kind=kind, bbox=SimpleNamespace(x=x, y=y, width=width, height=height))


def _fake_page(page_num: int, text: str, blocks=None):
    return SimpleNamespace(page_num=page_num, text=text, blocks=blocks or [])


def _fake_screenshot(page_num: int, image_bytes: bytes = b"png-bytes"):
    return SimpleNamespace(page_num=page_num, image_bytes=image_bytes)


def test_process_document_for_a_url_creates_one_page_and_one_chunk(monkeypatch):
    monkeypatch.setattr(tasks, "backend_client", MagicMock())
    monkeypatch.setattr(tasks, "fetch_url_markdown", lambda url: "# Hello\n\nSome content")
    tasks.backend_client.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com",
        "storage_key": None,
    }

    tasks.process_document("doc-1")

    tasks.backend_client.update_status.assert_any_call("doc-1", status="indexing", progress=0)
    tasks.backend_client.add_page.assert_called_once_with("doc-1", page_number=1, content="# Hello\n\nSome content")
    tasks.backend_client.add_chunk.assert_called_once()
    tasks.backend_client.update_status.assert_any_call("doc-1", status="indexed", progress=100)


def test_process_document_for_a_file_writes_pages_screenshots_and_chunks_with_bbox(monkeypatch):
    monkeypatch.setattr(tasks, "backend_client", MagicMock())
    monkeypatch.setattr(tasks, "storage", MagicMock())
    tasks.backend_client.get_document.return_value = {
        "id": "doc-2",
        "type": "file",
        "name": "report.pdf",
        "storage_key": "docs/report.pdf",
    }
    tasks.storage.get_object.return_value = b"pdf-bytes"

    parsed_page = _fake_page(1, "Full page text", blocks=[_fake_block("First paragraph"), _fake_block("", kind="rule")])
    fake_result = SimpleNamespace(pages=[parsed_page], screenshots=[_fake_screenshot(1)])
    monkeypatch.setattr(tasks, "parse_file", lambda data: fake_result)

    tasks.process_document("doc-2")

    tasks.storage.get_object.assert_called_once_with("docs/report.pdf")
    tasks.storage.put_object.assert_called_once_with(
        "screenshots/doc-2/page-1.png", b"png-bytes", content_type="image/png"
    )
    tasks.backend_client.add_page.assert_called_once_with(
        "doc-2", page_number=1, content="Full page text", screenshot="screenshots/doc-2/page-1.png"
    )
    # The empty-text "rule" block is skipped - only the paragraph becomes a chunk.
    tasks.backend_client.add_chunk.assert_called_once()
    call_kwargs = tasks.backend_client.add_chunk.call_args.kwargs
    assert call_kwargs["text"] == "First paragraph"
    assert call_kwargs["extras"] == {
        "kind": "paragraph",
        "page": 1,
        "bbox": {"x": 1.0, "y": 2.0, "width": 100.0, "height": 20.0},
    }
    tasks.backend_client.update_status.assert_any_call("doc-2", status="indexed", progress=100)


def test_process_document_reports_error_status_on_failure(monkeypatch):
    monkeypatch.setattr(tasks, "backend_client", MagicMock())
    tasks.backend_client.get_document.return_value = {
        "id": "doc-3",
        "type": "file",
        "name": "broken.pdf",
        "storage_key": None,
    }

    try:
        tasks.process_document("doc-3")
    except ValueError:
        pass

    status_calls = [
        call.kwargs.get("status") or call.args[1] for call in tasks.backend_client.update_status.call_args_list
    ]
    assert "error" in status_calls
