from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.chunking import PageText
from app.tasks.qa import locate_evidence

PAGES = [
    PageText(page_number=3, content="Introduction.\n\nLe télétravail est autorisé\ndeux jours par semaine."),
    PageText(page_number=4, content="Les congés payés sont de vingt-cinq jours par an."),
]


def test_a_quote_found_in_the_text_gives_its_page_and_is_kept_as_the_passage():
    page, excerpt = locate_evidence(PAGES, "Les congés payés sont de vingt-cinq jours par an.")

    assert page == 4
    assert excerpt == "Les congés payés sont de vingt-cinq jours par an."


def test_the_match_ignores_line_breaks_and_case():
    page, excerpt = locate_evidence(PAGES, "le TÉLÉTRAVAIL est autorisé deux jours par semaine.")

    assert page == 3
    assert excerpt == "le TÉLÉTRAVAIL est autorisé deux jours par semaine."


def test_a_quote_that_is_not_in_the_text_is_dropped():
    assert locate_evidence(PAGES, "Le télétravail est autorisé trois jours par semaine pour tous.") is None


@pytest.mark.parametrize("quote", ["", "   ", "Oui.", "télétravail"])
def test_an_empty_or_too_short_quote_is_dropped(quote):
    assert locate_evidence(PAGES, quote) is None


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    fake.get_collection_settings.return_value = {
        "instructions": {"qa": ""},
        "embedding_model": "emb",
        "generation_models": {"qa": "chat"},
    }
    fake.get_pages.return_value = [{"page_number": p.page_number, "content": p.content} for p in PAGES]
    fake.embed.return_value = [0.1]
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    return fake


def test_a_generated_pair_is_stored_with_the_page_and_passage_of_its_evidence(backend, monkeypatch):
    monkeypatch.setattr(
        tasks._shared,
        "_chat_json",
        lambda model, prompt, text: [
            {
                "question": "Combien de jours de télétravail ?",
                "answer": "Deux.",
                "evidence": "Le télétravail est autorisé deux jours par semaine.",
            },
            {
                "question": "Et les congés ?",
                "answer": "Vingt-cinq jours.",
                "evidence": "Une phrase inventée par le modèle.",
            },
        ],
    )

    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 2)

    (call,) = backend.replace_generated_qa.call_args_list
    first, second = call.args[3]
    assert first["source_page"] == 3
    assert first["source_excerpt"] == "Le télétravail est autorisé deux jours par semaine."
    # An evidence that isn't in the text is never shown as a source.
    assert second["source_page"] is None and second["source_excerpt"] is None


def test_the_model_is_asked_for_the_exact_evidence(backend, monkeypatch):
    prompts = []
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: prompts.append(prompt) or [])

    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 2)

    assert "evidence" in prompts[0] and "word for word" in prompts[0]


def test_a_pair_without_any_evidence_is_still_stored(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: [{"question": "Q ?", "answer": "R."}])

    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 1)

    backend.replace_generated_qa.assert_called_once()
    (pair,) = backend.replace_generated_qa.call_args.args[3]
    assert pair["source_page"] is None


def test_a_window_is_recorded_as_one_run_replacing_the_previous_extraction_of_it(backend, monkeypatch):
    """The task run twice - a redelivery after a crash - leaves the pairs of one run (#299): everything
    the window generated goes in one call, keyed by the window."""
    monkeypatch.setattr(
        tasks._shared,
        "_chat_json",
        lambda model, prompt, text: [{"question": "A ?", "answer": "a"}, {"question": "B ?", "answer": "b"}],
    )

    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 2)
    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 2)

    first, second = backend.replace_generated_qa.call_args_list
    assert first.args[:3] == second.args[:3] == ("col-1", "doc-1", "window:3-4")
    assert [pair["question"] for pair in first.args[3]] == ["A ?", "B ?"]


def test_a_window_that_generates_nothing_still_replaces_the_previous_run(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: [])

    tasks.generate_qa_window("doc-1", "col-1", 3, 4, 2)

    backend.replace_generated_qa.assert_called_once_with("col-1", "doc-1", "window:3-4", [])


def test_collection_level_pairs_are_keyed_by_the_description_they_are_about(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "_chat_json", lambda model, prompt, text: [{"question": "Q ?", "answer": "R."}])
    backend.get_collection_settings.return_value["pipeline_windows"] = {}

    tasks.generate_collection_qa("doc-1", "col-1", "Une collection sur les widgets.")
    tasks.generate_collection_qa("doc-1", "col-1", "Une collection sur les widgets.")
    tasks.generate_collection_qa("doc-1", "col-1", "Une autre description.")

    keys = [call.args[2] for call in backend.replace_generated_qa.call_args_list]
    # A replay replaces its own pairs; another description's are another run.
    assert keys[0] == keys[1] != keys[2]
    assert all(
        call.args[1] is None and key.startswith("collection:")
        for call, key in zip(backend.replace_generated_qa.call_args_list, keys, strict=True)
    )
