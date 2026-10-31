"""The check of the answer's claims, made once the answer is out."""

import json

from app.graph.nodes import ground_check as ground_check_module
from app.graph.nodes.ground_check import ground_check


def excerpt(id_: str, content: str, **extra) -> dict:
    return {"id": id_, "content": content, **extra}


class Model:
    def __init__(self, reply: dict | str) -> None:
        self.reply, self.calls = reply, []

    def add_run_event(self, *args, **kwargs):
        pass

    def get_active_prompt(self, name):
        return None

    def llm_chat(self, model, messages, max_tokens=None):
        self.calls.append(messages)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def state(**overrides):
    base = {
        "run_id": "run-1",
        "chat_model": "m",
        "answer": "Vingt-cinq jours [aaaa1111].",
        "answer_context": {"excerpts": [excerpt("aaaa1111", "Vingt-cinq jours de congés.")]},
        "citations": [{"evidence_id": "aaaa1111", "cited": True, "quote": "Vingt-cinq jours"}],
    }
    return {**base, **overrides}


def run(monkeypatch, model, **overrides):
    from app.graph.services import events, llm, prompts

    for module in (ground_check_module, events, llm, prompts):
        monkeypatch.setattr(module, "backend_client", model)
    prompts._cache.clear()
    return ground_check(state(**overrides))


def test_a_supported_answer_is_valid_with_one_model_call(monkeypatch):
    model = Model({"valid": True, "unsupported_claims": []})

    result = run(monkeypatch, model)

    assert result["valid"] is True and result["unsupported_claims"] == []
    assert len(model.calls) == 1
    assert "Vingt-cinq jours de congés." in model.calls[0][1]["content"]


def test_a_claim_no_excerpt_supports_is_reported(monkeypatch):
    model = Model({"valid": False, "unsupported_claims": ["Le télétravail est illimité"]})

    result = run(monkeypatch, model)

    assert result["valid"] is False and result["unsupported_claims"] == ["Le télétravail est illimité"]


def test_a_cited_passage_the_excerpt_does_not_have_is_found_without_the_model(monkeypatch):
    model = Model({"valid": True, "unsupported_claims": []})

    result = run(monkeypatch, model, citations=[{"evidence_id": "aaaa1111", "cited": True, "quote": None}])

    assert result["unverified_citations"] == ["aaaa1111"]


def test_a_reply_that_is_not_a_verdict_counts_as_valid_rather_than_blaming_the_answer(monkeypatch):
    result = run(monkeypatch, Model("n'importe quoi"))

    assert result["valid"] is True


def test_nothing_to_check_makes_no_model_call(monkeypatch):
    model = Model({"valid": False})

    assert run(monkeypatch, model, answer_context={"excerpts": []}) is None
    assert run(monkeypatch, model, answer="") is None
    assert run(monkeypatch, model, chat_model=None) is None
    assert model.calls == []
