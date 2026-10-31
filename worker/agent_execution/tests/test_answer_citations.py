"""An answer is attached to its sources (#402): its markers are checked against the excerpts it was given, and the ones
that point to nothing are taken off."""

import json
from typing import Any

from app.graph.nodes import generate_answer as generate_answer_module
from app.graph.services import events as events_module
from app.graph.services import prompts as prompts_module
from app.graph.services.citations import (
    CITATION_RULE,
    OUTPUT_FORMAT,
    cited_ids,
    find_passage,
    parse_answer,
    partial_answer,
    resolve_passages,
    without_invented_markers,
)

FIRST = "0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a"
SECOND = "7e1d2c3b-4a59-4687-8795-a4b3c2d1e0f9"
UNKNOWN = "11111111-2222-4333-8444-555555555555"
IDS = {FIRST, SECOND}


class Model:
    """The backend as the node sees it: the model answers `replies` in turn, and every call it receives is kept."""

    def __init__(self, replies: list[str], admin_prompt: str | None = None) -> None:
        self.replies, self.calls = list(replies), []
        self.admin_prompt = admin_prompt
        self.partials: list[str] = []

    def get_run(self, run_id):
        return {"cancel_requested": False}

    def update_run_status(self, *args, **kwargs):
        pass

    def add_run_event(self, *args, **kwargs):
        pass

    def set_partial_answer(self, run_id, text):
        self.partials.append(text)

    def get_active_prompt(self, name):
        return {"id": "v1", "content": self.admin_prompt} if self.admin_prompt else None

    def llm_chat_stream(self, model, messages, max_tokens=None):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        yield {"delta": reply[: len(reply) // 2]}
        yield {"delta": reply[len(reply) // 2 :]}
        yield {"done": True, "prompt_tokens": 10, "completion_tokens": 5}

    def llm_chat_with_usage(self, model, messages, max_tokens=None):
        self.calls.append(messages)
        return {"content": self.replies.pop(0), "prompt_tokens": 10, "completion_tokens": 5}


def excerpt(id_: str, **extra) -> dict[str, Any]:
    return {
        "id": id_,
        "content": f"Contenu de {id_[:4]}",
        "source": "politique.pdf",
        "tool": "search",
        "vdb_id": "hr",
        "evidence_kind": "document",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "qa_source": None,
        "page_number": 1,
        "url": None,
        "query": "q",
        "charts": [],
        **extra,
    }


def run(monkeypatch, model: Model, excerpts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    for module in (generate_answer_module, events_module, prompts_module):
        monkeypatch.setattr(module, "backend_client", model)
    monkeypatch.setattr(prompts_module, "_cache", {})
    state = {
        "run_id": "run-1",
        "chat_model": "m",
        "contextualized_query": "Combien de jours de congé ?",
        "web_search_enabled": False,
        "accessible_vdbs": [{"id": "hr", "name": "RH", "description": "", "tags": []}],
        "unexplored_vdb_ids": [],
        "answer_context": {
            "excerpts": [excerpt(FIRST), excerpt(SECOND)] if excerpts is None else excerpts,
            "coverage_insufficient": False,
            "missing_information": [],
        },
    }
    return generate_answer_module.generate_answer(state)


# --- the markers ---


def test_the_ids_an_answer_cites_are_those_of_its_excerpts_in_order():
    answer = f"Vingt-cinq jours [{SECOND}]. Posés avant mai [{FIRST}, {UNKNOWN}]. Encore [{SECOND}]."

    assert cited_ids(answer, IDS) == [SECOND, FIRST]
    assert cited_ids("Pas de source.", IDS) == []
    assert cited_ids(f"Inventé [{UNKNOWN}]", IDS) == []


def test_an_invented_id_is_dropped_from_its_bracket_and_an_empty_bracket_goes_with_its_space():
    answer = f"Un fait [{UNKNOWN}]. Un autre [{FIRST},{UNKNOWN}] et [{SECOND}]."

    assert without_invented_markers(answer, IDS) == f"Un fait. Un autre [{FIRST}] et [{SECOND}]."
    assert without_invented_markers("Rien à retirer [1].", IDS) == "Rien à retirer [1]."


# --- the answer ---


def test_an_answer_that_cites_its_excerpts_is_kept_and_only_the_cited_ones_are_marked(monkeypatch):
    model = Model([f"Vingt-cinq jours [{FIRST}]."])

    result = run(monkeypatch, model)

    assert result["answer"] == f"Vingt-cinq jours [{FIRST}]." and len(model.calls) == 1
    assert {c["evidence_id"]: c["cited"] for c in result["citations"]} == {FIRST: True, SECOND: False}


def test_an_answer_with_no_marker_is_kept_and_not_asked_for_again(monkeypatch):
    model = Model(["Vingt-cinq jours."])

    result = run(monkeypatch, model)

    # One call: a second one would cost as much as the first, and the interface says the answer has no source.
    assert result["answer"] == "Vingt-cinq jours." and len(model.calls) == 1
    assert {c["evidence_id"]: c["cited"] for c in result["citations"]} == {FIRST: False, SECOND: False}


def test_an_invented_marker_does_not_count_as_a_citation(monkeypatch):
    model = Model([f"Vingt-cinq jours [{UNKNOWN}]."])

    result = run(monkeypatch, model)

    assert UNKNOWN not in result["answer"] and len(model.calls) == 1
    assert not any(c["cited"] for c in result["citations"])


def test_the_citation_rule_is_kept_when_the_administrable_prompt_is_overridden(monkeypatch):
    model = Model([f"Oui [{FIRST}]"], admin_prompt="Réponds en vers.")

    run(monkeypatch, model)

    system = model.calls[0][0]["content"]
    assert system.startswith("Réponds en vers.") and system.endswith(CITATION_RULE + OUTPUT_FORMAT)


def test_an_excerpt_with_no_source_name_is_given_to_the_model_by_its_tool(monkeypatch):
    model = Model([f"Il est tard [{FIRST}]"])

    run(monkeypatch, model, [excerpt(FIRST, source=None, tool="time")])

    assert f"[{FIRST}] (source: time)" in model.calls[0][1]["content"]


def test_no_evidence_means_no_call_to_the_model_and_an_explicit_answer(monkeypatch):
    model = Model([])

    result = run(monkeypatch, model, [])

    assert model.calls == [] and result["citations"] == []
    assert "couldn't find any relevant information" in result["answer"]


# --- the structured answer (passages by id, in the raw text of the excerpt) ---

CONTENT = (
    "Les agents ont droit à vingt-cinq jours de congé annuel.\nCes jours se posent par demi-journées, avec l'accord de "
    "la hiérarchie.\nLe congé parental est réglé à part (voir le chapitre suivant)."
)


def structured(answer: str, *sources: tuple[str, str]) -> str:
    return json.dumps({"answer": answer, "sources": [{"id": i, "quote": q} for i, q in sources]})


def test_the_answer_is_read_from_the_json_as_it_is_written():
    raw = structured('Vingt-cinq jours "net"\net plus [x]', (FIRST, "abc"))
    quote_at = raw.index('\\"net')

    assert partial_answer(raw[:5]) == "" and partial_answer(raw[:12]) == ""
    assert partial_answer(raw[: quote_at + 0]) == "Vingt-cinq jours "
    assert partial_answer(raw[: quote_at + 1]) == "Vingt-cinq jours "  # an escape cut in two waits for its end
    assert partial_answer(raw[: quote_at + 2]) == 'Vingt-cinq jours "'
    assert partial_answer(raw) == 'Vingt-cinq jours "net"\net plus [x]'  # the sources are not part of it
    accent = structured("Café")
    assert partial_answer(accent[: accent.index("\\u00e9") + 3]) == "Caf"
    assert partial_answer(accent) == "Café"


def test_a_model_that_writes_plain_text_is_shown_as_it_writes():
    assert partial_answer("Vingt-cinq jours [x") == "Vingt-cinq jours [x"
    assert partial_answer('```json\n{"answer": "Vingt') == "Vingt"


def test_the_answer_and_its_sources_are_read_from_the_json_whatever_surrounds_it():
    raw = structured("Oui [a]", (FIRST, "un passage"))

    assert parse_answer(raw) == ("Oui [a]", [{"id": FIRST, "quote": "un passage"}])
    assert parse_answer("```json\n" + raw + "\n```")[0] == "Oui [a]"
    assert parse_answer("Voici : " + raw + " Fin.")[0] == "Oui [a]"


def test_text_that_is_not_the_asked_json_is_the_answer_with_no_source():
    assert parse_answer("Vingt-cinq jours.") == ("Vingt-cinq jours.", [])
    assert parse_answer('{"réponse": "x"}') == ('{"réponse": "x"}', [])
    assert parse_answer('{"answer": "Oui", "sources": "oops"}') == ("Oui", [])


def test_a_passage_is_found_in_the_excerpt_and_given_as_the_excerpt_has_it():
    found = find_passage("vingt-cinq  jours de CONGÉ annuel", CONTENT)

    assert found is not None
    assert found.text == "vingt-cinq jours de congé annuel" or found.text.lower() == "vingt-cinq jours de congé annuel"
    assert CONTENT[found.start : found.end] == found.text
    assert found.text == "vingt-cinq jours de congé annuel"


def test_what_copying_loses_does_not_make_another_passage():
    # a line break and the indentation, curly quotes, a hyphen at the end of a line
    assert find_passage("par demi-journées,\n   avec l’accord", CONTENT) is not None
    assert find_passage("informa-\ntion utile", "Une information utile pour tous") is not None
    found = find_passage("par demi-journées, avec l'accord de la hiérarchie", CONTENT)
    assert found is not None and found.text == "par demi-journées, avec l'accord de la hiérarchie"


def test_a_passage_with_a_word_changed_or_too_short_is_not_found():
    assert find_passage("les agents ont droit à trente jours de congé", CONTENT) is None
    assert find_passage("congé", CONTENT) is None
    assert find_passage("", CONTENT) is None
    assert find_passage("tout autre sujet sans rapport", CONTENT) is None


def test_the_passage_is_the_text_of_the_excerpt_by_its_id():
    excerpts = [excerpt(FIRST, content=CONTENT), excerpt(SECOND, content="Autre texte, sans rapport.")]
    sources = [
        {"id": FIRST, "quote": "vingt-cinq jours de congé annuel"},
        {"id": SECOND, "quote": "ce passage n'est pas dans cet extrait"},
        {"id": UNKNOWN, "quote": "vingt-cinq jours de congé annuel"},
    ]

    resolved = resolve_passages(sources, excerpts)

    assert set(resolved) == {FIRST, SECOND} and resolved[SECOND] is None
    assert resolved[FIRST] is not None and resolved[FIRST].text == "vingt-cinq jours de congé annuel"


def test_the_better_of_two_passages_for_an_id_is_kept():
    excerpts = [excerpt(FIRST, content=CONTENT)]
    sources = [
        {"id": FIRST, "quote": "du texte inventé par le modèle"},
        {"id": FIRST, "quote": "vingt-cinq jours de congé"},
    ]

    assert resolve_passages(sources, excerpts)[FIRST] is not None


def test_a_citation_carries_the_passage_of_the_excerpt_and_where_it_is(monkeypatch):
    model = Model([structured(f"Vingt-cinq jours [{FIRST}].", (FIRST, "VINGT-CINQ JOURS DE CONGÉ ANNUEL"))])

    result = run(monkeypatch, model, [excerpt(FIRST, content=CONTENT), excerpt(SECOND)])

    first, second = result["citations"]
    assert first["cited"] and first["quote"] == "vingt-cinq jours de congé annuel"
    assert CONTENT[first["quote_start"] : first["quote_end"]] == first["quote"]
    assert not second["cited"] and second["quote"] is None and second["quote_start"] is None


def test_a_citation_whose_passage_is_not_in_the_excerpt_is_kept_without_passage(monkeypatch):
    model = Model([structured(f"Trente jours [{FIRST}].", (FIRST, "les agents ont droit à trente jours"))])

    result = run(monkeypatch, model, [excerpt(FIRST, content=CONTENT)])

    [citation] = result["citations"]
    assert citation["cited"] is True and citation["quote"] is None and citation["quote_end"] is None
    assert len(model.calls) == 1  # a cited excerpt with a wrong passage is not an answer without a source


def test_the_sources_listed_are_citations_even_without_a_marker_in_the_text(monkeypatch):
    model = Model([structured("Vingt-cinq jours.", (SECOND, "Contenu de 7e1d"))])

    result = run(monkeypatch, model)

    assert {c["evidence_id"]: c["cited"] for c in result["citations"]} == {FIRST: False, SECOND: True}
    assert len(model.calls) == 1


def test_a_source_that_is_no_excerpt_is_ignored(monkeypatch):
    model = Model([structured("Vingt-cinq jours.", (UNKNOWN, "un passage"))])

    result = run(monkeypatch, model)

    assert len(model.calls) == 1 and result["answer"] == "Vingt-cinq jours."
    assert not any(c["cited"] for c in result["citations"])


def test_the_chat_is_shown_the_answer_as_it_is_written_not_the_json(monkeypatch):
    model = Model([structured(f"Vingt-cinq jours [{FIRST}].", (FIRST, "Contenu de 0b9f"))])

    run(monkeypatch, model)

    assert model.partials[0] == ""
    assert all("{" not in partial and "sources" not in partial for partial in model.partials)
    assert any(p.startswith("Vingt") for p in model.partials)
