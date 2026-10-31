"""Les fichiers copiés d'un autre système (#457) : un résumé par fichier, et la description de leur collection."""

from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.config import settings
from app.tasks import copied


def test_fictional_pages_cut_the_text_by_a_number_of_words():
    pages = copied.fictional_pages("un deux trois quatre cinq six sept", 3)

    assert [(page.page_number, page.content) for page in pages] == [
        (1, "un deux trois"),
        (2, "quatre cinq six"),
        (3, "sept"),
    ]


def test_fictional_pages_of_an_empty_text_are_none():
    assert copied.fictional_pages("  \n ", 500) == []


def test_fictional_pages_never_loop_on_a_zero_size():
    assert len(copied.fictional_pages("a b c", 0)) == 3


@pytest.fixture
def backend(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", client)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    client.get_document.return_value = {"id": "doc-1", "summary": None, "content_hash": "a" * 64}
    client.get_pages.return_value = [{"page_number": 1, "content": " ".join(f"mot{i}" for i in range(1200))}]
    client.get_collection_settings.return_value = {
        "instructions": {"summary": "Be brief."},
        "generation_models": {"summary": "llm"},
        "embedding_model": "bge",
        "pipeline_windows": {"summary_pages_per_map": 2},
    }
    client.llm_chat.side_effect = lambda model, messages: f"résumé({len(messages[-1]['content'].split())})"
    client.embed.return_value = [0.1, 0.2]
    return client


def test_a_copied_file_is_summarized_by_fictional_pages_and_keeps_its_single_page(backend, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SUMMARY_WORDS_PER_PAGE", 500)

    copied.summarize_copied_document.run("doc-1", "col-1")

    # 1200 words = 3 fictional pages, 2 per map: two partial summaries, then their combination.
    assert backend.llm_chat.call_count == 3
    assert backend.llm_chat.call_args_list[0].args[1][-1]["content"].count("mot") == 1000
    backend.embed.assert_called_once()
    assert backend.embed.call_args.args[0] == "bge"
    # The summary reads the whole text: no stretch of pages is reported, and no page is written.
    document_id, summary, embedding = backend.set_document_summary.call_args.args
    assert (document_id, embedding) == ("doc-1", [0.1, 0.2])
    assert backend.set_document_summary.call_args.kwargs == {"pages": None}
    backend.add_page.assert_not_called()


def test_a_long_copied_file_is_read_whole_whatever_the_sampling_of_the_collection(backend, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SUMMARY_WORDS_PER_PAGE", 5)
    backend.get_collection_settings.return_value["pipeline_windows"] = {
        "summary_pages_per_map": 50,
        "sampling_min_pages": 10,
        "summary_mode": "percent",
        "summary_percent": 10,
    }

    copied.summarize_copied_document.run("doc-1", "col-1")

    # 240 fictional pages are past the threshold: a real document would be sampled, this one is not.
    assert sum(call.args[1][-1]["content"].count("mot") for call in backend.llm_chat.call_args_list[:5]) == 1200
    assert backend.set_document_summary.call_args.kwargs == {"pages": None}


def test_a_file_that_has_a_summary_costs_nothing(backend):
    backend.get_document.return_value = {"id": "doc-1", "summary": "déjà"}

    copied.summarize_copied_document.run("doc-1", "col-1")

    backend.llm_chat.assert_not_called()
    backend.embed.assert_not_called()
    backend.set_document_summary.assert_not_called()
    tasks._shared._spawn.assert_not_called()


def test_a_file_without_text_is_not_summarized(backend):
    backend.get_pages.return_value = []

    copied.summarize_copied_document.run("doc-1", "col-1")

    backend.llm_chat.assert_not_called()
    backend.set_document_summary.assert_not_called()


def test_the_summary_of_a_file_starts_nothing_after_it(backend):
    copied.summarize_copied_document.run("doc-1", "col-1")

    tasks._shared._spawn.assert_not_called()


def test_a_summary_that_fails_is_reported_on_the_document(backend):
    backend.llm_chat.side_effect = RuntimeError("hub down")

    with pytest.raises(RuntimeError):
        copied.summarize_copied_document.run("doc-1", "col-1")

    backend.set_document_error.assert_called_once()
