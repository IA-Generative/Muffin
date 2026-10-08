import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app import task_logging, tasks
from app.agent import EditFailedError
from app.config import settings
from app.contract import EditJobInput
from app.preview import PreviewError
from tests.odt_fixture import PNG, build_odt

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
    monkeypatch.setattr(tasks, "convert_to_pdf", lambda data: b"%PDF-fake")
    monkeypatch.setattr(tasks, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(settings, "EDIT_LLM_MODEL", "")
    return storage, backend


def test_edit_document_runs_the_agent_and_stores_the_edited_draft(fake_io):
    storage, backend = fake_io

    result = tasks.edit_document.apply(args=[_payload()], task_id="job-1").get()

    storage.get_object.assert_called_once_with("documents/col-1/abc-procedure.odt")
    key, data = storage.put_object.call_args_list[0].args
    assert key == "drafts/doc-1/job-1.odt"
    assert data != storage.get_object.return_value
    assert storage.put_object.call_args_list[0].kwargs["content_type"] == "application/vnd.oasis.opendocument.text"
    assert result["draft_storage_key"] == "drafts/doc-1/job-1.odt"
    assert result["edited"] is True
    assert result["operations_summary"] == "- Paragraphe ajouté à la fin de « Contacts »."
    assert result["pending_images"] == [
        {"id": "img-1", "description": "Plan d'accès", "section": None, "after_paragraph": None}
    ]
    assert result["preview_pdf_key"] == "drafts/doc-1/job-1.pdf"
    assert backend.llm_chat.call_args.args[0] == "hub-model"
    # The ODT's PDF preview is stored next to the draft...
    assert storage.put_object.call_args_list[1].args == ("drafts/doc-1/job-1.pdf", b"%PDF-fake")
    assert storage.put_object.call_args_list[1].kwargs["content_type"] == "application/pdf"
    # ...and the backend is told what the job produced, which is what makes the draft ready.
    backend.report_draft_result.assert_called_once()
    job_id, reported = backend.report_draft_result.call_args.args
    assert job_id == "job-1"
    assert reported["kind"] == "edit"
    assert reported["draft_storage_key"] == "drafts/doc-1/job-1.odt"
    assert reported["preview_pdf_key"] == "drafts/doc-1/job-1.pdf"
    assert reported["edited"] is True


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
    # The backend is told, with a message fit for the user, so the draft doesn't stay "pending".
    backend.report_draft_result.assert_not_called()
    job_id, message = backend.report_draft_failure.call_args.args
    assert job_id == "job-6"
    assert "2 tentative(s)" in message
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


def test_an_unexpected_error_is_reported_without_leaking_its_details(fake_io):
    storage, backend = fake_io
    storage.get_object.side_effect = RuntimeError("secret internal detail")

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-9")

    assert outcome.failed()
    assert backend.report_draft_failure.call_args.args == ("job-9", "L'édition a échoué (erreur interne).")


def test_a_failing_report_to_the_backend_does_not_hide_the_original_failure(fake_io):
    _, backend = fake_io
    backend.llm_chat.return_value = "pas du JSON"
    backend.report_draft_failure.side_effect = RuntimeError("backend down")

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-10")

    assert outcome.failed()
    assert isinstance(outcome.result, EditFailedError)


def test_a_request_the_model_declines_has_no_preview_to_render(fake_io, monkeypatch):
    storage, backend = fake_io
    backend.llm_chat.return_value = json.dumps({"operations": [], "message": "Rien à changer."})
    convert = MagicMock()
    monkeypatch.setattr(tasks, "convert_to_pdf", convert)

    result = tasks.edit_document.apply(args=[_payload()], task_id="job-11").get()

    convert.assert_not_called()
    assert result["preview_pdf_key"] is None
    assert backend.report_draft_result.call_args.args[1]["edited"] is False


def test_a_markdown_draft_has_no_pdf_preview(fake_io, monkeypatch):
    storage, _ = fake_io
    storage.get_object.return_value = b"# Contacts\n\nRH : rh@example.org\n"
    convert = MagicMock()
    monkeypatch.setattr(tasks, "convert_to_pdf", convert)

    result = tasks.edit_document.apply(args=[_payload(format="md")], task_id="job-12").get()

    convert.assert_not_called()
    assert result["preview_pdf_key"] is None
    assert storage.put_object.call_count == 1


def test_a_preview_that_cannot_be_rendered_fails_the_job_with_a_clear_message(fake_io, monkeypatch):
    _, backend = fake_io

    def broken(_data):
        raise PreviewError("la conversion en PDF a échoué")

    monkeypatch.setattr(tasks, "convert_to_pdf", broken)

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-13")

    assert outcome.failed()
    message = backend.report_draft_failure.call_args.args[1]
    assert "son aperçu n'a pas pu être généré" in message


# -- insert_images ------------------------------------------------------------------------------


def _images_payload(**overrides):
    payload = {
        "draft_storage_key": "drafts/doc-1/job-1.odt",
        "document_id": "doc-1",
        "user_id": "user-1",
        "images": [
            {
                "id": "img-1",
                "description": "Plan d'accès",
                "storage_key": "drafts/doc-1/images/img-1",
                "section": {"heading": "Contacts"},
                "after_paragraph": 1,
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_insert_images_adds_the_uploads_to_the_draft_and_renders_a_new_preview(fake_io):
    storage, backend = fake_io
    odt = build_odt()
    storage.get_object.side_effect = lambda key: PNG if key.endswith("img-1") else odt

    result = tasks.insert_images_task.apply(args=[_images_payload()], task_id="job-20").get()

    assert result["draft_storage_key"] == "drafts/doc-1/job-20.odt"
    assert result["preview_pdf_key"] == "drafts/doc-1/job-20.pdf"
    assert result["operations_summary"] == "- Image « Plan d'accès » insérée après le paragraphe 1 de « Contacts »."
    edited = storage.put_object.call_args_list[0].args[1]
    assert b"Pictures/" in edited and edited != odt
    reported = backend.report_draft_result.call_args.args[1]
    assert reported["kind"] == "images"
    assert reported["draft_storage_key"] == "drafts/doc-1/job-20.odt"


def test_insert_images_fails_clearly_on_an_unsupported_image_and_reports_it(fake_io):
    storage, backend = fake_io
    odt = build_odt()
    storage.get_object.side_effect = lambda key: b"GIF-ish nonsense" if key.endswith("img-1") else odt

    outcome = tasks.insert_images_task.apply(args=[_images_payload()], task_id="job-21")

    assert outcome.failed()
    assert "PNG, JPEG et GIF" in backend.report_draft_failure.call_args.args[1]
    storage.put_object.assert_not_called()
