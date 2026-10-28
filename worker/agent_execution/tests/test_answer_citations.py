"""An answer is attached to its sources (#402): its markers are checked against the excerpts it was given, and an answer
that cites nothing is asked for again, once."""

from typing import Any

from app.graph.nodes import generate_answer as generate_answer_module
from app.graph.services import events as events_module
from app.graph.services import prompts as prompts_module
from app.graph.services.citations import CITATION_RULE, cited_ids, without_invented_markers

FIRST = "0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a"
SECOND = "7e1d2c3b-4a59-4687-8795-a4b3c2d1e0f9"
UNKNOWN = "11111111-2222-4333-8444-555555555555"
IDS = {FIRST, SECOND}


class Model:
    """The backend as the node sees it: the model answers `replies` in turn, and every call it receives is kept."""

    def __init__(self, replies: list[str], admin_prompt: str | None = None) -> None:
        self.replies, self.calls = list(replies), []
        self.admin_prompt = admin_prompt

    def get_run(self, run_id):
        return {"cancel_requested": False}

    def update_run_status(self, *args, **kwargs):
        pass

    def add_run_event(self, *args, **kwargs):
        pass

    def set_partial_answer(self, run_id, text):
        pass

    def get_active_prompt(self, name):
        return {"id": "v1", "content": self.admin_prompt} if self.admin_prompt else None

    def llm_chat_stream(self, model, messages, max_tokens=None):
        self.calls.append(messages)
        yield {"delta": self.replies.pop(0)}
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


def test_an_answer_with_no_marker_is_asked_for_again_with_its_citations(monkeypatch):
    model = Model(["Vingt-cinq jours.", f"Vingt-cinq jours [{SECOND}]."])

    result = run(monkeypatch, model)

    assert result["answer"] == f"Vingt-cinq jours [{SECOND}]."
    assert len(model.calls) == 2
    retry = model.calls[1]
    assert retry[-2] == {"role": "assistant", "content": "Vingt-cinq jours."}
    assert "cites none" in retry[-1]["content"]
    assert {c["evidence_id"]: c["cited"] for c in result["citations"]} == {FIRST: False, SECOND: True}
    assert result["answer_prompt_tokens"] == 20 and result["answer_completion_tokens"] == 10


def test_an_invented_marker_does_not_count_as_a_citation(monkeypatch):
    model = Model([f"Vingt-cinq jours [{UNKNOWN}].", f"Vingt-cinq jours [{FIRST}]."])

    result = run(monkeypatch, model)

    assert UNKNOWN not in result["answer"] and result["answer"] == f"Vingt-cinq jours [{FIRST}]."
    assert len(model.calls) == 2


def test_an_answer_that_still_cites_nothing_is_kept_and_asked_for_only_once(monkeypatch):
    model = Model(["Vingt-cinq jours.", "Vingt-cinq jours, vraiment."])

    result = run(monkeypatch, model)

    assert result["answer"] == "Vingt-cinq jours." and len(model.calls) == 2
    assert not any(c["cited"] for c in result["citations"]) and len(result["citations"]) == 2


def test_the_citation_rule_is_kept_when_the_administrable_prompt_is_overridden(monkeypatch):
    model = Model([f"Oui [{FIRST}]"], admin_prompt="Réponds en vers.")

    run(monkeypatch, model)

    system = model.calls[0][0]["content"]
    assert system.startswith("Réponds en vers.") and system.endswith(CITATION_RULE)


def test_an_excerpt_with_no_source_name_is_given_to_the_model_by_its_tool(monkeypatch):
    model = Model([f"Il est tard [{FIRST}]"])

    run(monkeypatch, model, [excerpt(FIRST, source=None, tool="time")])

    assert f"[{FIRST}] (source: time)" in model.calls[0][1]["content"]


def test_no_evidence_means_no_call_to_the_model_and_an_explicit_answer(monkeypatch):
    model = Model([])

    result = run(monkeypatch, model, [])

    assert model.calls == [] and result["citations"] == []
    assert "couldn't find any relevant information" in result["answer"]
