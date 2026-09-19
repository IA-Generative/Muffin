import json
from unittest.mock import MagicMock

from app import task_logging, tasks


def _message(role: str, content: str):
    return {"role": role, "content": content}


_TWO_TURN_TRANSCRIPT = [
    _message("user", "What is the telework policy?"),
    _message("assistant", "Telework is allowed 2 days per week."),
    _message("user", "And for managers?"),
    _message("assistant", "Managers follow the same policy."),
]


def test_score_discussion_persists_a_well_formed_judgment(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.list_conversation_messages.return_value = _TWO_TURN_TRANSCRIPT
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.return_value = json.dumps(
        {
            "coherent": True,
            "coherence_issues": [],
            "context_usage_score": 0.9,
            "context_usage_issues": [],
            "reasoning": "Consistent answers, context correctly reused.",
        }
    )
    fake.create_discussion_score.return_value = "score-1"

    tasks.score_discussion("conv-1")

    fake.llm_chat.assert_called_once()
    model, messages = fake.llm_chat.call_args.args
    assert model == "test-model"
    assert "Telework is allowed 2 days per week." in messages[1]["content"]

    fake.create_discussion_score.assert_called_once()
    conversation_id, payload = fake.create_discussion_score.call_args.args
    assert conversation_id == "conv-1"
    assert payload["message_count"] == 4
    assert payload["coherent"] is True
    assert payload["context_usage_score"] == 0.9
    assert payload["reasoning"] == "Consistent answers, context correctly reused."

    fake.set_task_logs.assert_called_once()


def test_score_discussion_falls_back_on_malformed_json(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.list_conversation_messages.return_value = _TWO_TURN_TRANSCRIPT
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.return_value = "not json at all"
    fake.create_discussion_score.return_value = "score-1"

    tasks.score_discussion("conv-1")

    fake.create_discussion_score.assert_called_once()
    _, payload = fake.create_discussion_score.call_args.args
    # Conservative fallback: no fabricated issues, not a crash.
    assert payload["coherent"] is True
    assert payload["coherence_issues"] == []
    assert payload["context_usage_score"] == 1.0


def test_score_discussion_skips_a_single_turn_conversation(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.list_conversation_messages.return_value = [
        _message("user", "What is the telework policy?"),
        _message("assistant", "2 days/week."),
    ]

    tasks.score_discussion("conv-1")

    fake.get_default_chat_model.assert_not_called()
    fake.llm_chat.assert_not_called()
    fake.create_discussion_score.assert_not_called()


def test_score_discussion_skips_without_a_chat_model(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.list_conversation_messages.return_value = _TWO_TURN_TRANSCRIPT
    fake.get_default_chat_model.return_value = None

    tasks.score_discussion("conv-1")

    fake.llm_chat.assert_not_called()
    fake.create_discussion_score.assert_not_called()


def test_score_discussion_strips_a_markdown_code_fence(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", fake)

    fake.list_conversation_messages.return_value = _TWO_TURN_TRANSCRIPT
    fake.get_default_chat_model.return_value = "test-model"
    fake.llm_chat.return_value = (
        "```json\n"
        + json.dumps({"coherent": False, "coherence_issues": ["contradiction"], "context_usage_score": 0.2})
        + "\n```"
    )
    fake.create_discussion_score.return_value = "score-1"

    tasks.score_discussion("conv-1")

    _, payload = fake.create_discussion_score.call_args.args
    assert payload["coherent"] is False
    assert payload["coherence_issues"] == ["contradiction"]
    assert payload["context_usage_score"] == 0.2
