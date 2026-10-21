"""A task run twice - a redelivery after a crash - leaves what one run leaves (#299): the worker's side
of it. What the backend does with a replayed write is tested there."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.scraping import FetchedUrl


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    monkeypatch.setattr(tasks._shared, "storage", MagicMock())
    fake.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "emb",
        "instructions": {"extraction": ""},
        "generation_models": {"extraction": "chat"},
        "pipeline_windows": {},
    }
    return fake


# -- pages and chunks ---------------------------------------------------------------------------


def test_the_pages_of_a_file_are_followed_by_a_drop_of_whatever_a_longer_run_left(backend, monkeypatch):
    backend.get_document.return_value = {
        "id": "doc-1",
        "type": "file",
        "name": "report.pdf",
        "storage_key": "k",
        "collection_id": "col-1",
    }
    tasks._shared.storage.get_object.return_value = b"pdf"
    pages = [SimpleNamespace(page_num=number, text=f"page {number}", blocks=[]) for number in (1, 2, 3)]
    monkeypatch.setattr(tasks._shared, "parse_file", lambda data: SimpleNamespace(pages=pages, screenshots=[]))

    tasks.process_document("doc-1")

    assert backend.add_page.call_count == 3
    backend.prune_pages.assert_called_once_with("doc-1", keep=3)


def test_an_html_page_is_one_page_and_nothing_after_it(backend, monkeypatch):
    backend.get_document.return_value = {
        "id": "doc-1",
        "type": "url",
        "name": "https://example.com",
        "storage_key": None,
        "collection_id": "col-1",
    }
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: FetchedUrl(markdown="# Page"))

    tasks.process_document("doc-1")

    backend.prune_pages.assert_called_once_with("doc-1", keep=1)


def test_the_chunks_are_followed_by_a_drop_of_those_a_previous_cut_left_after_them(backend):
    backend.get_pages.return_value = [{"page_number": 1, "content": "One.\n\nTwo.\n\nThree."}]

    tasks.chunk_document("doc-1", "col-1")

    written = backend.add_chunk.call_count
    assert written > 0
    backend.prune_chunks.assert_called_once_with("doc-1", keep=written)
    # Written first, pruned after: a failure in between leaves chunks, not an empty document.
    names = [call[0] for call in backend.method_calls if call[0] in ("add_chunk", "prune_chunks")]
    assert names[-1] == "prune_chunks"


def test_the_tabular_pipeline_has_no_chunks_to_prune(backend):
    backend.get_pages.return_value = [{"page_number": 1, "content": "a,b"}]

    tasks.chunk_document("doc-1", "col-1", skip_summary=True, skip_qa=True, skip_chunking=True, skip_extraction=True)

    backend.prune_chunks.assert_not_called()


# -- entities and relations ---------------------------------------------------------------------


def _extracted(entities, relations):
    return {"entities": entities, "relations": relations}


def test_the_entities_of_a_window_are_sent_in_one_call_keyed_by_the_window(backend, monkeypatch):
    backend.get_pages.return_value = [{"page_number": n, "content": f"page {n}"} for n in (3, 4)]
    monkeypatch.setattr(
        tasks._shared,
        "_chat_json",
        lambda model, prompt, text: _extracted(
            [
                {"name": "Acme", "type": "organisation"},
                {"name": "Acme", "type": "organisation"},
                {"name": "Alice", "type": "personne"},
            ],
            [{"from": "Alice", "to": "Acme", "type": "works_at"}, {"from": "Alice", "to": "Nobody", "type": "knows"}],
        ),
    )

    tasks.extract_entities_window("doc-1", "col-1", 3, 4)

    backend.replace_entity_window.assert_called_once_with(
        "doc-1",
        "pages:3-4",
        # The same entity listed twice is one entity mentioned twice.
        [{"name": "Acme", "type": "organisation", "mentions": 2}, {"name": "Alice", "type": "personne", "mentions": 1}],
        # A relation naming an entity that was not extracted is dropped.
        [{"from_name": "Alice", "to_name": "Acme", "type": "works_at"}],
    )


def test_a_replayed_window_sends_the_same_replacement(backend, monkeypatch):
    backend.get_pages.return_value = [{"page_number": 1, "content": "page"}]
    monkeypatch.setattr(
        tasks._shared, "_chat_json", lambda model, prompt, text: _extracted([{"name": "Acme", "type": "lieu"}], [])
    )

    tasks.extract_entities_window("doc-1", "col-1", 1, 2)
    tasks.extract_entities_window("doc-1", "col-1", 1, 2)

    first, second = backend.replace_entity_window.call_args_list
    assert first == second


def test_a_window_with_nothing_found_still_replaces_the_previous_extraction(backend, monkeypatch):
    backend.get_pages.return_value = [{"page_number": 1, "content": "page"}]
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: _extracted([], []))

    tasks.extract_entities_window("doc-1", "col-1", 1, 2)

    backend.replace_entity_window.assert_called_once_with("doc-1", "pages:1-2", [], [])
