"""Les fichiers copiés d'un autre système (#457) : un résumé par fichier, et la description de leur collection."""

import random
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


LONG = "mot " * 200  # 800 characters, over DESCRIBE_MIN_CHARS


def _metadata(description: str, indexed: bool) -> dict:
    return {"description": description, "tags": [], "document_summaries": [], "description_indexed": indexed}


@pytest.fixture
def sample(backend):
    """A collection of three distinct files, one of them too short to count, and a model that answers in turn."""
    backend.list_collection_documents.return_value = [
        {"id": "d1", "name": "a.pdf"},
        {"id": "d2", "name": "b.pdf"},
        {"id": "d3", "name": "short.pdf"},
    ]
    texts = {"d1": LONG, "d2": LONG, "d3": "trop court"}
    backend.get_pages.side_effect = lambda document_id: [{"page_number": 1, "content": texts[document_id]}]
    backend.get_default_embedding_model.return_value = "default-embed"
    backend.llm_chat.side_effect = None
    return backend


def _answers(backend, *answers: str) -> None:
    backend.llm_chat.side_effect = list(answers)


def test_the_sample_is_distinct_names_with_enough_text(sample):
    excerpts = copied.sample_excerpts("col-1", random.Random(1))

    assert sorted(excerpt.split("\n")[0] for excerpt in excerpts) == ["### a.pdf", "### b.pdf"]


def test_a_source_cut_into_many_files_of_one_name_is_seen_through_the_others_too(sample, monkeypatch):
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_FILES", 3)
    sample.list_collection_documents.return_value = [{"id": "d1", "name": "big.pdf"}] * 50 + [
        {"id": "d2", "name": "b.pdf"}
    ]

    names = {e.split("\n")[0] for e in copied.sample_excerpts("col-1", random.Random(1))}

    assert names == {"### big.pdf", "### b.pdf"}


def test_the_sample_is_limited_in_files_and_in_characters(sample, monkeypatch):
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_FILES", 1)
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_CHARS", 50)

    [excerpt] = copied.sample_excerpts("col-1", random.Random(1))

    assert len(excerpt.split("\n", 1)[1]) == 50


def test_an_empty_description_is_made_from_the_sample_and_indexed(sample):
    sample.get_collection_metadata.return_value = _metadata("", False)
    _answers(sample, "résumé de l'échantillon", "Procédures de la CNIL.")

    copied.describe_copied_collection.run("col-1")

    sample.update_collection_description.assert_called_once_with("col-1", "Procédures de la CNIL.")
    sample.update_collection_description_embedding.assert_called_once()
    assert sample.embed.call_args.args[0] == "default-embed"
    # The model is told what a description is, and given the summary of the sample, not the sample itself.
    system, user = (m["content"] for m in sample.llm_chat.call_args.args[1])
    assert "Elle commence directement par le sujet" in system
    assert user == "résumé de l'échantillon"


def test_a_description_the_model_finds_wrong_is_replaced(sample):
    sample.get_collection_metadata.return_value = _metadata("Ancienne", True)
    _answers(sample, "résumé", "Nouvelle description.")

    copied.describe_copied_collection.run("col-1")

    sample.update_collection_description.assert_called_once_with("col-1", "Nouvelle description.")
    assert "Ancienne" in sample.llm_chat.call_args.args[1][-1]["content"]


def test_a_description_the_model_keeps_is_indexed_when_it_never_was(sample):
    sample.get_collection_metadata.return_value = _metadata("Celle d'Open WebUI", False)
    _answers(sample, "résumé", "INCHANGÉE")

    copied.describe_copied_collection.run("col-1")

    sample.update_collection_description.assert_not_called()
    sample.update_collection_description_embedding.assert_called_once()


def test_a_description_that_stays_and_is_indexed_asks_nothing_more(sample):
    sample.get_collection_metadata.return_value = _metadata("Celle d'Open WebUI", True)
    _answers(sample, "résumé", "Inchangée.")

    copied.describe_copied_collection.run("col-1")

    sample.update_collection_description.assert_not_called()
    sample.update_collection_description_embedding.assert_not_called()


def test_a_collection_without_text_is_left_alone(sample):
    sample.get_pages.side_effect = lambda document_id: [{"page_number": 1, "content": "court"}]

    copied.describe_copied_collection.run("col-1")

    sample.llm_chat.assert_not_called()
    sample.update_collection_description.assert_not_called()
