"""The check of the grounding of an answer (#402): what the judge reads, what it reports, and what is done with it."""

import json
from typing import Any

import pytest

from app.config import settings
from app.graph.nodes import validate_grounding as validate_module
from app.graph.nodes.rewrite_citations import rewrite_citations
from app.graph.routing.conditions import after_generate_answer, after_validate_grounding
from app.graph.services import events as events_module
from app.graph.services import llm as llm_module
from app.graph.services import prompts as prompts_module

FIRST = "0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a"
SECOND = "7e1d2c3b-4a59-4687-8795-a4b3c2d1e0f9"
UNKNOWN = "11111111-2222-4333-8444-555555555555"


class Judge:
    """The backend as the node sees it: the judge answers `reply`, and what it was asked is kept."""

    def __init__(self, reply: Any, admin_prompt: str | None = None) -> None:
        self.reply, self.admin_prompt, self.calls = reply, admin_prompt, []

    def get_run(self, run_id):
        return {"cancel_requested": False}

    def update_run_status(self, *args, **kwargs):
        pass

    def add_run_event(self, run_id, type_, data=None, task_id=None):
        self.calls.append(("event", type_, data))

    def get_active_prompt(self, name):
        return {"id": "v1", "content": self.admin_prompt} if self.admin_prompt else None

    def llm_chat(self, model, messages, max_tokens=None):
        self.calls.append(("chat", messages))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)

    @property
    def asked(self) -> list[dict[str, str]]:
        return next(call[1] for call in self.calls if call[0] == "chat")

    @property
    def events(self) -> dict[str, Any]:
        return {call[1]: call[2] for call in self.calls if call[0] == "event"}


def excerpt(id_: str, content: str = "Un contenu.", **extra) -> dict[str, Any]:
    return {"id": id_, "content": content, **extra}


def grounded(monkeypatch, judge: Judge, excerpts: list[dict[str, Any]], citations=None) -> dict[str, Any]:
    for module in (events_module, llm_module, prompts_module):
        monkeypatch.setattr(module, "backend_client", judge)
    monkeypatch.setattr(prompts_module, "_cache", {})
    state = {
        "run_id": "run-1",
        "chat_model": "m",
        "answer": f"Vingt-cinq jours [{FIRST}].",
        "answer_context": {"excerpts": excerpts},
        "citations": citations or [],
    }
    return validate_module.validate_grounding(state)["grounding_result"]


# --- what the judge reads ---


def test_the_judge_reads_the_whole_of_a_short_excerpt_and_not_its_first_500_characters(monkeypatch):
    content = "début " * 150 + "la phrase qui compte est tout à la fin."
    judge = Judge({"valid": True, "unsupported_claims": []})

    grounded(monkeypatch, judge, [excerpt(FIRST, content)])

    assert "la phrase qui compte est tout à la fin." in judge.asked[1]["content"]


def test_around_the_cited_passage_the_judge_reads_the_excerpt_of_a_long_one(monkeypatch):
    content = "a" * 5000 + " LE PASSAGE CITÉ ICI " + "b" * 5000
    start = content.index("LE PASSAGE")
    judge = Judge({"valid": True, "unsupported_claims": []})

    grounded(
        monkeypatch,
        judge,
        [excerpt(FIRST, content, quote="LE PASSAGE CITÉ ICI", quote_start=start, quote_end=start + 19)],
    )

    asked = judge.asked[1]["content"]
    assert "LE PASSAGE CITÉ ICI" in asked and "(cited passage: «LE PASSAGE CITÉ ICI»)" in asked
    assert len(asked) < 3000


def test_the_check_of_the_citations_is_kept_when_the_administrable_prompt_is_overridden(monkeypatch):
    judge = Judge({"valid": True, "unsupported_claims": []}, admin_prompt="Juge en vers.")

    grounded(monkeypatch, judge, [excerpt(FIRST)])

    system = judge.asked[0]["content"]
    assert system.startswith("Juge en vers.") and "miscited_claims" in system and "uncited_claims" in system


# --- what it reports ---


def test_it_reports_what_is_unsupported_miscited_and_uncited(monkeypatch):
    judge = Judge(
        {
            "valid": False,
            "unsupported_claims": ["une date inventée"],
            "miscited_claims": [
                {"claim": "25 jours", "cited": FIRST, "supported_by": SECOND},
                {"claim": "id inventé", "cited": UNKNOWN, "supported_by": None},
                {"claim": "mauvais soutien", "cited": SECOND, "supported_by": UNKNOWN},
                "pas un objet",
            ],
            "uncited_claims": ["le congé se pose par demi-journées", "", 3],
        }
    )

    result = grounded(monkeypatch, judge, [excerpt(FIRST), excerpt(SECOND)])

    assert result["valid"] is False and result["unsupported_claims"] == ["une date inventée"]
    assert result["miscited_claims"] == [
        {"claim": "25 jours", "cited": FIRST, "supported_by": SECOND},
        {"claim": "mauvais soutien", "cited": SECOND, "supported_by": None},
    ]
    assert result["uncited_claims"] == ["le congé se pose par demi-journées"]
    assert judge.events["grounding_validation_completed"]["uncited_claims"] == result["uncited_claims"]


def test_a_cited_passage_the_excerpt_does_not_have_is_reported_without_asking_the_model(monkeypatch):
    citations = [
        {"evidence_id": FIRST, "cited": True, "quote": "un passage vrai"},
        {"evidence_id": SECOND, "cited": True, "quote": None},
        {"evidence_id": UNKNOWN, "cited": False, "quote": None},
    ]

    result = grounded(monkeypatch, Judge({"valid": True}), [excerpt(FIRST), excerpt(SECOND)], citations)

    assert result["unverified_citations"] == [SECOND]


def test_a_judge_that_fails_or_answers_something_else_finds_nothing_to_say(monkeypatch):
    for reply in (RuntimeError("down"), "pas du JSON", {"autre": 1}):
        result = grounded(monkeypatch, Judge(reply), [excerpt(FIRST)])

        assert result["valid"] is True and result["unsupported_claims"] == []
        assert result["miscited_claims"] == [] and result["uncited_claims"] == []


def test_no_evidence_means_nothing_to_check_and_no_call(monkeypatch):
    judge = Judge({"valid": False})

    result = grounded(monkeypatch, judge, [])

    assert result["valid"] is True and [c for c in judge.calls if c[0] == "chat"] == []


# --- what is done with it ---


def state_after(grounding: dict[str, Any], research=0, rewrites=0) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "grounding_result": {"unsupported_claims": [], "miscited_claims": [], "uncited_claims": [], **grounding},
        "grounding_research_count": research,
        "citation_rewrites": rewrites,
    }


@pytest.fixture(autouse=True)
def _no_cancellation(monkeypatch):
    monkeypatch.setattr("app.graph.routing.conditions.is_cancelled", lambda run_id: False)


def test_an_unsupported_claim_is_searched_for_again_as_before():
    assert after_validate_grounding(state_after({"valid": False, "unsupported_claims": ["x"]})) == "targeted_research"


def test_a_claim_cited_wrongly_or_not_at_all_has_the_answer_written_again():
    miscited = [{"claim": "c", "cited": FIRST, "supported_by": None}]

    assert after_validate_grounding(state_after({"valid": True, "miscited_claims": miscited})) == "rewrite_citations"
    assert after_validate_grounding(state_after({"valid": True, "uncited_claims": ["c"]})) == "rewrite_citations"


def test_the_answer_is_written_again_once_only():
    assert after_validate_grounding(state_after({"valid": True, "uncited_claims": ["c"]}, rewrites=1)) == "end"


def test_when_the_search_is_spent_the_citations_are_still_put_right():
    exhausted = settings.MAX_GROUNDING_RESEARCHES
    grounding = {"valid": False, "unsupported_claims": ["x"], "uncited_claims": ["c"]}

    assert after_validate_grounding(state_after(grounding, research=exhausted)) == "rewrite_citations"
    assert (
        after_validate_grounding(state_after({"valid": False, "unsupported_claims": ["x"]}, research=exhausted))
        == "end"
    )


def test_a_sound_answer_ends():
    assert after_validate_grounding(state_after({"valid": True})) == "end"
    assert after_validate_grounding(state_after({"valid": True, "unverified_citations": [FIRST]})) == "end"


def test_the_node_hands_the_claims_to_the_next_writing_and_counts_it(monkeypatch):
    monkeypatch.setattr("app.graph.nodes.rewrite_citations.is_cancelled", lambda run_id: False)
    monkeypatch.setattr("app.graph.nodes.rewrite_citations.emit", lambda *a, **k: None)
    monkeypatch.setattr("app.graph.nodes.rewrite_citations.set_activity", lambda *a, **k: None)
    state = state_after(
        {
            "valid": True,
            "miscited_claims": [{"claim": "25 jours", "cited": FIRST, "supported_by": SECOND}],
            "uncited_claims": ["demi-journées"],
        }
    )

    update = rewrite_citations(state)

    assert update["citation_rewrites"] == 1
    assert update["citation_feedback"] == [
        f"25 jours (cited {FIRST}, supported by {SECOND})",
        "demi-journées (cites nothing)",
    ]


def test_an_answer_written_again_for_its_citations_is_not_checked_a_second_time(monkeypatch):
    monkeypatch.setattr("app.graph.routing.conditions.is_cancelled", lambda run_id: False)
    state = {
        "run_id": "r",
        "citation_rewrites": 1,
        "completed_task_ids": [],
        "research_tasks": [],
        "query_analysis": {},
    }

    assert after_generate_answer(state) == "end"
