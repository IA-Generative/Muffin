from types import SimpleNamespace
from unittest.mock import MagicMock

from app import task_logging, tasks


def _fake_block(text: str, kind: str = "paragraph", bbox=(1.0, 2.0, 100.0, 20.0)):
    x, y, width, height = bbox
    return SimpleNamespace(text=text, kind=kind, bbox=SimpleNamespace(x=x, y=y, width=width, height=height))


def _fake_page(page_num: int, text: str, blocks=None):
    return SimpleNamespace(page_num=page_num, text=text, blocks=blocks or [])


def _fake_screenshot(page_num: int, image_bytes: bytes = b"png-bytes"):
    return SimpleNamespace(page_num=page_num, image_bytes=image_bytes)


def test_process_document_for_a_url_creates_one_page_and_one_chunk(monkeypatch):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    monkeypatch.setattr(tasks._shared, "fetch_url_markdown", lambda url: "# Hello\n\nSome content")
    tasks._shared.backend_client.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com",
        "storage_key": None,
        "collection_id": "col-1",
    }
    tasks._shared.backend_client.get_pages.return_value = []

    tasks.process_document("doc-1")

    tasks._shared.backend_client.update_status.assert_any_call("doc-1", status="indexing", progress=0)
    tasks._shared.backend_client.add_page.assert_called_once_with(
        "doc-1", page_number=1, content="# Hello\n\nSome content"
    )
    tasks._shared.backend_client.update_status.assert_any_call("doc-1", status="indexing", progress=50)
    tasks._shared._spawn.assert_called_once()
    spawned_task, spawned_args = (
        tasks._shared._spawn.call_args.args[0],
        tasks._shared._spawn.call_args.args[1],
    )
    assert spawned_task.name == "app.tasks.chunk_document"
    assert spawned_args == ["doc-1", "col-1"]


def test_process_document_for_a_file_writes_pages_screenshots_and_chunks_with_bbox(
    monkeypatch,
):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    monkeypatch.setattr(tasks._shared, "storage", MagicMock())
    tasks._shared.backend_client.get_document.return_value = {
        "id": "doc-2",
        "type": "file",
        "name": "report.pdf",
        "storage_key": "docs/report.pdf",
        "collection_id": "col-2",
    }
    tasks._shared.backend_client.get_pages.return_value = []
    tasks._shared.storage.get_object.return_value = b"pdf-bytes"

    parsed_page = _fake_page(
        1,
        "Full page text",
        blocks=[_fake_block("First paragraph"), _fake_block("", kind="rule")],
    )
    fake_result = SimpleNamespace(pages=[parsed_page], screenshots=[_fake_screenshot(1)])
    monkeypatch.setattr(tasks._shared, "parse_file", lambda data: fake_result)

    tasks.process_document("doc-2")

    tasks._shared.storage.get_object.assert_called_once_with("docs/report.pdf")
    tasks._shared.storage.put_object.assert_called_once_with(
        "screenshots/doc-2/page-1.png", b"png-bytes", content_type="image/png"
    )
    tasks._shared.backend_client.add_page.assert_called_once_with(
        "doc-2",
        page_number=1,
        content="Full page text",
        screenshot="screenshots/doc-2/page-1.png",
    )
    tasks._shared.backend_client.update_status.assert_any_call("doc-2", status="indexing", progress=50)
    tasks._shared._spawn.assert_called_once()
    spawned_task, spawned_args = (
        tasks._shared._spawn.call_args.args[0],
        tasks._shared._spawn.call_args.args[1],
    )
    assert spawned_task.name == "app.tasks.chunk_document"
    assert spawned_args == ["doc-2", "col-2"]


def test_chunk_document_embeds_each_chunk_with_the_collections_own_model(monkeypatch):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    tasks._shared.backend_client.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "pipeline_windows": {},
    }
    tasks._shared.backend_client.get_pages.return_value = [{"page_number": 1, "content": "Some page content.\n\nMore."}]
    tasks._shared.backend_client.embed.return_value = [0.1, 0.2, 0.3]

    tasks.chunk_document("doc-4", "col-4")

    assert tasks._shared.backend_client.embed.call_count >= 1
    for call in tasks._shared.backend_client.embed.call_args_list:
        assert call.args[0] == "text-embedding-3-small"

    add_chunk_calls = tasks._shared.backend_client.add_chunk.call_args_list
    assert add_chunk_calls
    for call in add_chunk_calls:
        assert call.kwargs["embedding"] == [0.1, 0.2, 0.3]


def test_chunk_document_tolerates_embedding_failures(monkeypatch):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    tasks._shared.backend_client.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "pipeline_windows": {},
    }
    tasks._shared.backend_client.get_pages.return_value = [{"page_number": 1, "content": "Some page content."}]
    tasks._shared.backend_client.embed.side_effect = RuntimeError("LLM hub unavailable")

    tasks.chunk_document("doc-5", "col-5")

    for call in tasks._shared.backend_client.add_chunk.call_args_list:
        assert call.kwargs["embedding"] is None
    tasks._shared.backend_client.update_status.assert_any_call("doc-5", status="indexed", progress=100)


def test_process_document_reports_error_status_on_failure(monkeypatch):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    tasks._shared.backend_client.get_document.return_value = {
        "id": "doc-3",
        "type": "file",
        "name": "broken.pdf",
        "storage_key": None,
        "collection_id": "col-3",
    }

    try:
        tasks.process_document("doc-3")
    except ValueError:
        pass

    status_calls = [
        call.kwargs.get("status") or call.args[1] for call in tasks._shared.backend_client.update_status.call_args_list
    ]
    assert "error" in status_calls


def test_chunk_document_with_skip_chunking_skips_chunking_but_still_indexes(
    monkeypatch,
):
    """Tabular pipeline passes skip_chunking=True: no chunks are created,
    but the document is still marked indexed and tagging/extraction are
    dispatched."""
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    tasks._shared.backend_client.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "pipeline_windows": {},
    }
    tasks._shared.backend_client.get_pages.return_value = [{"page_number": 1, "content": "Some page content."}]

    tasks.chunk_document("doc-6", "col-6", skip_summary=True, skip_qa=True, skip_chunking=True)

    # No chunks created
    tasks._shared.backend_client.add_chunk.assert_not_called()
    tasks._shared.backend_client.embed.assert_not_called()
    # Still marked indexed
    tasks._shared.backend_client.update_status.assert_any_call("doc-6", status="indexed", progress=100)
    # Tagging and extraction still dispatched (skip_summary only skips summarize_document,
    # but tagging is dispatched by summarize_document — so with skip_summary=True,
    # neither summarize_document nor tag_document are dispatched)
    # Extraction is always dispatched
    spawn_calls = tasks._shared._spawn.call_args_list
    spawned_names = [call.args[2] for call in spawn_calls]
    assert "app.tasks.extract_entities_window" in spawned_names
