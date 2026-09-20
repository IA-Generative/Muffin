from typing import Any
from unittest.mock import MagicMock

from app.agent_service import AgentService


def _completed_state(**overrides: Any) -> dict[str, Any]:
    state = {
        "conversation_id": "conv-1",
        "original_query": "What is the leave policy?",
        "answer": "Leave is 25 days per year [abc].",
        "citations": [{"evidence_id": "abc", "source": "policy.pdf", "vdb_id": "hr"}],
    }
    state.update(overrides)
    return state


def test_finalize_generates_a_conversation_title_after_a_completed_run(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.return_value = "Leave policy question"
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", _completed_state())

    fake.update_conversation_title.assert_called_once_with("conv-1", "Leave policy question")


def test_finalize_strips_quotes_and_length_caps_the_generated_title(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.return_value = '  "' + ("x" * 100) + '"  '
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", _completed_state())

    title = fake.update_conversation_title.call_args.args[1]
    assert not title.startswith('"')
    assert len(title) <= 80


def test_finalize_skips_title_generation_without_a_chat_model(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = None
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", _completed_state())

    fake.llm_chat.assert_not_called()
    fake.update_conversation_title.assert_not_called()


def test_finalize_does_not_fail_the_run_if_title_generation_errors(monkeypatch):
    """A title-generation failure must never flip an already-completed run to failed - it's a
    best-effort side effect, not part of what makes the run itself succeed."""
    fake = MagicMock()
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.side_effect = RuntimeError("LLM hub unavailable")
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", _completed_state())  # must not raise

    fake.update_run_status.assert_called_once_with("run-1", "completed")


def test_finalize_does_not_generate_a_title_for_a_cancelled_run(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", {"cancelled": True})

    fake.get_default_chat_model.assert_not_called()


def test_finalize_reports_the_grounding_verdict_alongside_the_result(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = None
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize(
        "run-1",
        _completed_state(
            grounding_result={"valid": False, "unsupported_claims": ["25 days is a minimum, not a guarantee"]},
            grounding_research_count=2,
        ),
    )

    fake.set_run_result.assert_called_once_with(
        "run-1",
        "Leave is 25 days per year [abc].",
        [{"evidence_id": "abc", "source": "policy.pdf", "vdb_id": "hr"}],
        grounding_valid=False,
        grounding_unsupported_claims=["25 days is a minimum, not a guarantee"],
        grounding_research_count=2,
        latency_ms=None,
        prompt_tokens=None,
        completion_tokens=None,
    )


def test_finalize_reports_no_grounding_verdict_when_validate_grounding_was_skipped(monkeypatch):
    """after_generate_answer can route straight to END without ever running validate_grounding
    (e.g. no evidence to check) - grounding_result stays None in that case, not a fabricated
    "valid" verdict."""
    fake = MagicMock()
    fake.get_default_chat_model.return_value = None
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize("run-1", _completed_state())

    fake.set_run_result.assert_called_once_with(
        "run-1",
        "Leave is 25 days per year [abc].",
        [{"evidence_id": "abc", "source": "policy.pdf", "vdb_id": "hr"}],
        grounding_valid=None,
        grounding_unsupported_claims=None,
        grounding_research_count=None,
        latency_ms=None,
        prompt_tokens=None,
        completion_tokens=None,
    )


def test_finalize_persists_pending_human_action_on_interrupt(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    interrupt = MagicMock()
    interrupt.value = {"question": "Which department do you mean?"}

    AgentService()._finalize("run-1", {"__interrupt__": [interrupt]})

    fake.update_run_status.assert_called_once_with("run-1", "waiting_for_user")
    fake.update_run_state.assert_called_once_with(
        "run-1", pending_human_action={"question": "Which department do you mean?"}
    )
    fake.get_default_chat_model.assert_not_called()
