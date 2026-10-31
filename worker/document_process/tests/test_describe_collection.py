"""La description d'une collection faite d'un échantillon de ses fichiers (#457)."""

import random
from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.config import settings
from app.tasks import describe


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
    excerpts = describe.sample_excerpts("col-1", random.Random(1))

    assert sorted(excerpt.split("\n")[0] for excerpt in excerpts) == ["### a.pdf", "### b.pdf"]


def test_a_source_cut_into_many_files_of_one_name_is_seen_through_the_others_too(sample, monkeypatch):
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_FILES", 3)
    sample.list_collection_documents.return_value = [{"id": "d1", "name": "big.pdf"}] * 50 + [
        {"id": "d2", "name": "b.pdf"}
    ]

    names = {e.split("\n")[0] for e in describe.sample_excerpts("col-1", random.Random(1))}

    assert names == {"### big.pdf", "### b.pdf"}


def test_the_sample_is_limited_in_files_and_in_characters(sample, monkeypatch):
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_FILES", 1)
    monkeypatch.setattr(settings, "DESCRIBE_SAMPLE_CHARS", 50)

    [excerpt] = describe.sample_excerpts("col-1", random.Random(1))

    assert len(excerpt.split("\n", 1)[1]) == 50


def test_an_empty_description_is_made_from_the_sample_and_indexed(sample):
    sample.get_collection_metadata.return_value = _metadata("", False)
    _answers(sample, "résumé de l'échantillon", "Procédures de la CNIL.")

    describe.describe_collection.run("col-1")

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

    describe.describe_collection.run("col-1")

    sample.update_collection_description.assert_called_once_with("col-1", "Nouvelle description.")
    assert "Ancienne" in sample.llm_chat.call_args.args[1][-1]["content"]


def test_a_description_the_model_keeps_is_indexed_when_it_never_was(sample):
    sample.get_collection_metadata.return_value = _metadata("Celle d'Open WebUI", False)
    _answers(sample, "résumé", "INCHANGÉE")

    describe.describe_collection.run("col-1")

    sample.update_collection_description.assert_not_called()
    sample.update_collection_description_embedding.assert_called_once()


def test_a_description_that_stays_and_is_indexed_asks_nothing_more(sample):
    sample.get_collection_metadata.return_value = _metadata("Celle d'Open WebUI", True)
    _answers(sample, "résumé", "Inchangée.")

    describe.describe_collection.run("col-1")

    sample.update_collection_description.assert_not_called()
    sample.update_collection_description_embedding.assert_not_called()


def test_a_collection_without_text_is_left_alone(sample):
    sample.get_pages.side_effect = lambda document_id: [{"page_number": 1, "content": "court"}]

    describe.describe_collection.run("col-1")

    sample.llm_chat.assert_not_called()
    sample.update_collection_description.assert_not_called()
