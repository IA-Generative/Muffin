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
        edit_proposal=None,
        unexplored_collection_ids=[],
        questions=None,
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
        edit_proposal=None,
        unexplored_collection_ids=[],
        questions=None,
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


def test_finalize_hands_the_edit_proposal_to_the_backend_with_the_answer(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = None
    monkeypatch.setattr("app.agent_service.backend_client", fake)
    proposal = {"collection_id": "col-1", "document_id": "doc-1", "document_name": "procedure.odt"}

    AgentService()._finalize("run-1", _completed_state(edit_proposal=proposal))

    assert fake.set_run_result.call_args.kwargs["edit_proposal"] == proposal


def test_finalize_reports_unexplored_collections_once_and_only_accessible_ones(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.agent_service.backend_client", fake)

    AgentService()._finalize(
        "run-1",
        _completed_state(
            accessible_vdbs=[{"id": "leave"}, {"id": "hr"}],
            unexplored_vdb_ids=["leave", "gone", "leave", "hr"],
        ),
    )

    assert fake.set_run_result.call_args.kwargs["unexplored_collection_ids"] == ["leave", "hr"]


def test_finalize_hands_the_questions_to_the_backend_and_does_not_title_the_conversation(monkeypatch):
    fake = MagicMock()
    fake.get_default_chat_model.return_value = "test-model"
    monkeypatch.setattr("app.agent_service.backend_client", fake)
    questions = [{"question": "Which?", "header": "Which", "multi_select": False, "options": []}]

    AgentService()._finalize("run-1", _completed_state(answer="Which?", citations=[], questions=questions))

    assert fake.set_run_result.call_args.kwargs["questions"] == questions
    fake.update_run_status.assert_called_once_with("run-1", "completed")
    fake.llm_chat.assert_not_called()
    fake.update_conversation_title.assert_not_called()


def _run_row(history, **overrides):
    row = {
        "id": "run-1",
        "status": "queued",
        "user_id": "user-1",
        "conversation_id": "conv-1",
        "query": "Période : 2024",
        "history": history,
    }
    row.update(overrides)
    return row


def _run(monkeypatch, row):
    fake = MagicMock()
    fake.get_run.return_value = row
    fake.get_default_chat_model.return_value = "test-model"
    graph = MagicMock()
    graph.invoke.return_value = {"conversation_id": "conv-1", "answer": "ok", "citations": [], "original_query": "q"}
    monkeypatch.setattr("app.agent_service.backend_client", fake)
    monkeypatch.setattr("app.agent_service._graph", graph)
    AgentService().run("run-1")
    return fake, graph.invoke.call_args.args[0]


def test_an_answer_to_questions_is_announced_with_the_event_clients_already_know(monkeypatch):
    history = [
        {"role": "user", "content": "Combien de congés ?", "asked": False},
        {"role": "assistant", "content": "Quelle période ?\n- 2023\n- 2024", "asked": True},
    ]

    fake, state = _run(monkeypatch, _run_row(history))

    fake.add_run_event.assert_any_call("run-1", "clarification_received", {"answer": "Période : 2024"})
    assert state["question_rounds"] == 1
    assert state["messages"][-3:] == [
        {"role": "user", "content": "Combien de congés ?"},
        {"role": "assistant", "content": "Quelle période ?\n- 2023\n- 2024"},
        {"role": "user", "content": "Période : 2024"},
    ]


def test_a_plain_message_is_not_announced_as_an_answer(monkeypatch):
    history = [{"role": "assistant", "content": "Une réponse", "asked": False}]

    fake, state = _run(monkeypatch, _run_row(history))

    assert not [call for call in fake.add_run_event.call_args_list if call.args[1] == "clarification_received"]
    assert state["question_rounds"] == 0


def test_a_run_nobody_reads_is_told_so(monkeypatch):
    _, state = _run(monkeypatch, _run_row([], interactive=False))
    assert state["interactive"] is False

    _, state = _run(monkeypatch, _run_row([]))
    assert state["interactive"] is True
