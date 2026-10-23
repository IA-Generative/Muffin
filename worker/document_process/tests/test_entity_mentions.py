"""Where the entities are in the text of a window of pages, and the sentence behind each relation (#352)."""

from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.entity_mentions import MAX_PER_PAGE, find_mentions


class TestFindMentions:
    def test_a_name_is_found_wherever_it_is_in_order(self):
        content = "Acme Corp a signé. Plus tard, acme corp a payé."

        assert [content[start:end] for start, end in find_mentions(content, "Acme Corp")] == ["Acme Corp", "acme corp"]

    def test_the_words_of_a_name_may_be_separated_by_any_whitespace(self):
        content = "Jean\nDupont  dirige Acme."

        assert [content[start:end] for start, end in find_mentions(content, "Jean Dupont")] == ["Jean\nDupont"]

    def test_a_name_is_a_whole_word_never_the_start_of_another(self):
        assert find_mentions("Un Parisien à Paris.", "Paris") == [(14, 19)]
        assert find_mentions("Parisienne", "Paris") == []
        assert find_mentions("Le grand Paris.", "Paris") != []

    def test_a_name_with_characters_of_a_regular_expression_is_taken_literally(self):
        content = "Le langage C++ (ou C#) et A.B.C."

        assert [content[start:end] for start, end in find_mentions(content, "C++")] == ["C++"]
        assert [content[start:end] for start, end in find_mentions(content, "A.B.C.")] == ["A.B.C."]

    def test_a_name_that_is_everywhere_gives_a_few_places_not_all_of_them(self):
        assert len(find_mentions("Paris " * 100, "Paris")) == MAX_PER_PAGE
        assert len(find_mentions("Paris " * 100, "Paris", limit=3)) == 3

    def test_nothing_is_found_for_an_empty_or_one_letter_name_or_a_name_that_is_not_there(self):
        assert find_mentions("Un texte.", "") == []
        assert find_mentions("a b c", "a") == []
        assert find_mentions("Un texte.", "Acme") == []
        assert find_mentions("", "Acme") == []


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    fake.get_collection_settings.return_value = {
        "instructions": {"extraction": ""},
        "generation_models": {"extraction": "chat"},
    }
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    return fake


PAGES = [
    {"page_number": 1, "content": "Hors fenêtre : Acme Corp est ici aussi."},
    {
        "page_number": 2,
        "content": "Acme Corp est dirigée par Jean Dupont.\n\nJean Dupont dirige Acme Corp depuis dix ans.",
    },
    {"page_number": 3, "content": "Le contrat lie Acme Corp à ses clients."},
]


def _extract(monkeypatch, backend, entities, relations=(), start=2, end=3):
    backend.get_pages.return_value = PAGES
    monkeypatch.setattr(
        tasks._shared, "_chat_json", lambda model, prompt, text: {"entities": entities, "relations": list(relations)}
    )
    tasks.extract_entities_window("doc-1", "col-1", start, end)
    ((_, _, sent_entities, sent_relations),) = [call.args for call in backend.replace_entity_window.call_args_list]
    return {entity["name"]: entity for entity in sent_entities}, sent_relations


def test_an_entity_is_found_in_the_text_of_the_window_and_counted_as_often_as_it_is_there(backend, monkeypatch):
    entities, _ = _extract(
        monkeypatch,
        backend,
        # The model listed it once: it is there three times in the window (twice on page 2, once on page 3).
        [{"name": "Acme Corp", "type": "organisation"}],
    )

    acme = entities["Acme Corp"]
    assert acme["mentions"] == 3
    assert sorted(o["page"] for o in acme["occurrences"]) == [2, 2, 3]
    for occurrence in acme["occurrences"]:
        content = next(page["content"] for page in PAGES if page["page_number"] == occurrence["page"])
        assert content[occurrence["start"] : occurrence["end"]] == "Acme Corp"


def test_the_pages_outside_the_window_are_not_searched(backend, monkeypatch):
    entities, _ = _extract(monkeypatch, backend, [{"name": "Acme Corp", "type": "organisation"}], start=3, end=3)

    assert [o["page"] for o in entities["Acme Corp"]["occurrences"]] == [3]
    assert entities["Acme Corp"]["mentions"] == 1


def test_a_name_that_is_nowhere_in_the_text_keeps_the_times_the_model_listed_it_and_has_no_occurrence(
    backend, monkeypatch
):
    entities, _ = _extract(
        monkeypatch,
        backend,
        [{"name": "Société Acme", "type": "organisation"}, {"name": "Société Acme", "type": "organisation"}],
    )

    assert entities["Société Acme"]["mentions"] == 2
    assert entities["Société Acme"]["occurrences"] == []


def test_a_relation_keeps_the_sentence_behind_it_and_where_it_is(backend, monkeypatch):
    _, relations = _extract(
        monkeypatch,
        backend,
        [{"name": "Jean Dupont", "type": "personne"}, {"name": "Acme Corp", "type": "organisation"}],
        [
            {
                "from": "Jean Dupont",
                "to": "Acme Corp",
                "type": "dirige",
                "evidence": "Jean Dupont dirige Acme Corp depuis dix ans.",
            }
        ],
    )

    (relation,) = relations
    assert relation["source_page"] == 2
    assert relation["source_excerpt"] == "Jean Dupont dirige Acme Corp depuis dix ans."
    content = PAGES[1]["content"]
    assert content[relation["source_start"] : relation["source_end"]] == "Jean Dupont dirige Acme Corp depuis dix ans."


def test_a_sentence_the_model_made_up_is_dropped_and_the_relation_stays_without_it(backend, monkeypatch):
    _, relations = _extract(
        monkeypatch,
        backend,
        [{"name": "Jean Dupont", "type": "personne"}, {"name": "Acme Corp", "type": "organisation"}],
        [
            {
                "from": "Jean Dupont",
                "to": "Acme Corp",
                "type": "dirige",
                "evidence": "Jean Dupont a fondé Acme Corp en 1999.",
            },
            {"from": "Acme Corp", "to": "Jean Dupont", "type": "emploie"},
        ],
    )

    assert [(r["type"], "source_page" in r) for r in relations] == [("dirige", False), ("emploie", False)]


def test_a_sentence_from_outside_the_window_is_not_taken(backend, monkeypatch):
    _, relations = _extract(
        monkeypatch,
        backend,
        [{"name": "Acme Corp", "type": "organisation"}, {"name": "Jean Dupont", "type": "personne"}],
        [
            {
                "from": "Acme Corp",
                "to": "Jean Dupont",
                "type": "x",
                "evidence": "Hors fenêtre : Acme Corp est ici aussi.",
            }
        ],
        start=2,
        end=3,
    )

    assert "source_page" not in relations[0]


def test_the_model_is_asked_for_the_exact_sentence_of_each_relation(backend, monkeypatch):
    prompts = []
    backend.get_pages.return_value = PAGES
    monkeypatch.setattr(
        tasks._shared,
        "_chat_json",
        lambda model, prompt, text: prompts.append(prompt) or {"entities": [], "relations": []},
    )

    tasks.extract_entities_window("doc-1", "col-1", 2, 3)

    assert '"evidence"' in prompts[0] and "word for word" in prompts[0]
