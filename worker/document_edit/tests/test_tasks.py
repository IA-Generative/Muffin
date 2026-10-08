import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app import task_logging, tasks
from app.agent import EditFailedError
from app.config import settings
from app.contract import EditJobInput
from tests.odt_fixture import build_odt

REPLY = json.dumps(
    {
        "operations": [{"op": "insert_paragraph", "section": {"heading": "Contacts"}, "text": "Urgences : 15"}],
        "pending_images": [{"description": "Plan d'accès"}],
        "message": "Fait.",
    }
)


def _payload(**overrides):
    payload = {
        "source_storage_key": "documents/col-1/abc-procedure.odt",
        "prompt": "Ajoute un numéro d'urgence",
        "document_id": "doc-1",
        "base_revision": 3,
        "format": "odt",
        "user_id": "user-1",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def fake_io(monkeypatch):
    storage = MagicMock()
    storage.get_object.return_value = build_odt()
    backend = MagicMock()
    backend.get_default_chat_model.return_value = "hub-model"
    backend.llm_chat.return_value = REPLY
    monkeypatch.setattr(tasks, "storage", storage)
    monkeypatch.setattr(tasks, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(settings, "EDIT_LLM_MODEL", "")
    return storage, backend


def test_edit_document_runs_the_agent_and_stores_the_edited_draft(fake_io):
    storage, backend = fake_io

    result = tasks.edit_document.apply(args=[_payload()], task_id="job-1").get()

    storage.get_object.assert_called_once_with("documents/col-1/abc-procedure.odt")
    key, data = storage.put_object.call_args.args
    assert key == "drafts/doc-1/job-1.odt"
    assert data != storage.get_object.return_value
    assert storage.put_object.call_args.kwargs["content_type"] == "application/vnd.oasis.opendocument.text"
    assert result["draft_storage_key"] == "drafts/doc-1/job-1.odt"
    assert result["edited"] is True
    assert result["operations_summary"] == "- Paragraphe ajouté à la fin de « Contacts »."
    assert result["pending_images"] == [
        {"id": "img-1", "description": "Plan d'accès", "section": None, "after_paragraph": None}
    ]
    assert result["preview_pdf_key"] is None
    assert backend.llm_chat.call_args.args[0] == "hub-model"


def test_edit_document_starts_from_the_previous_draft_when_adjusting(fake_io):
    storage, _ = fake_io

    tasks.edit_document.apply(args=[_payload(previous_draft_key="drafts/doc-1/job-0.odt")], task_id="job-2").get()

    storage.get_object.assert_called_once_with("drafts/doc-1/job-0.odt")


def test_the_configured_model_wins_over_the_hubs_default(fake_io, monkeypatch):
    _, backend = fake_io
    monkeypatch.setattr(settings, "EDIT_LLM_MODEL", "edit-model")

    tasks.edit_document.apply(args=[_payload()], task_id="job-3").get()

    assert backend.llm_chat.call_args.args[0] == "edit-model"
    backend.get_default_chat_model.assert_not_called()


def test_edit_document_without_any_chat_model_fails_with_a_clear_message(fake_io):
    storage, backend = fake_io
    backend.get_default_chat_model.return_value = None

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-4")

    assert outcome.failed()
    assert "Aucun modèle de chat" in str(outcome.result)
    storage.put_object.assert_not_called()


def test_a_request_the_model_declines_stores_an_unchanged_copy_and_explains(fake_io):
    storage, backend = fake_io
    backend.llm_chat.return_value = json.dumps({"operations": [], "message": "Rien à changer."})

    result = tasks.edit_document.apply(args=[_payload()], task_id="job-5").get()

    assert result["edited"] is False
    assert result["operations_summary"] == "Rien à changer."
    assert storage.put_object.call_args.args[1] == storage.get_object.return_value


def test_an_edit_the_agent_cannot_produce_fails_the_task_and_reports_its_logs(fake_io, monkeypatch):
    storage, backend = fake_io
    backend.llm_chat.return_value = "pas du JSON"
    monkeypatch.setattr(settings, "EDIT_MAX_ATTEMPTS", 2)

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-6")

    assert outcome.failed()
    assert isinstance(outcome.result, EditFailedError)
    assert backend.llm_chat.call_count == 2
    storage.put_object.assert_not_called()
    logs = task_logging.backend_client.set_task_logs.call_args.args
    assert logs[0] == "job-6"
    assert "2 tentative(s)" in logs[1]


def test_a_markdown_job_uses_the_markdown_media_type_and_extension(fake_io):
    storage, _ = fake_io
    storage.get_object.return_value = b"# Contacts\n\nRH : rh@example.org\n"

    tasks.edit_document.apply(args=[_payload(format="md")], task_id="job-7").get()

    key, data = storage.put_object.call_args.args
    assert key == "drafts/doc-1/job-7.md"
    assert storage.put_object.call_args.kwargs["content_type"].startswith("text/markdown")
    assert data.decode().endswith("RH : rh@example.org\n\nUrgences : 15\n")


@pytest.mark.parametrize(
    "overrides",
    [{"prompt": ""}, {"base_revision": 0}, {"format": "pdf"}, {"source_storage_key": None}],
)
def test_the_input_contract_rejects_an_invalid_payload(overrides):
    with pytest.raises(ValidationError):
        EditJobInput.model_validate(_payload(**overrides))


def test_an_invalid_payload_fails_without_touching_storage_or_the_model(fake_io):
    storage, backend = fake_io

    outcome = tasks.edit_document.apply(args=[_payload(prompt="")], task_id="job-8")

    assert outcome.failed()
    storage.get_object.assert_not_called()
    backend.llm_chat.assert_not_called()
