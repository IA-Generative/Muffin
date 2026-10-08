from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app import task_logging, tasks
from app.contract import EditJobInput, EditJobResult


def _payload(**overrides):
    payload = {
        "source_storage_key": "documents/col-1/abc-procedure.odt",
        "prompt": "Ajoute une section sur le matériel",
        "document_id": "doc-1",
        "base_revision": 3,
        "format": "odt",
        "user_id": "user-1",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def fake_io(monkeypatch):
    fake_storage = MagicMock()
    fake_storage.get_object.return_value = b"odt-bytes"
    monkeypatch.setattr(tasks, "storage", fake_storage)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    return fake_storage


def test_edit_document_copies_the_source_into_a_draft_and_reports_it_unedited(fake_io):
    result = tasks.edit_document.apply(args=[_payload()], task_id="job-1").get()

    fake_io.get_object.assert_called_once_with("documents/col-1/abc-procedure.odt")
    fake_io.put_object.assert_called_once_with(
        "drafts/doc-1/job-1.odt", b"odt-bytes", content_type="application/vnd.oasis.opendocument.text"
    )
    assert result == EditJobResult(draft_storage_key="drafts/doc-1/job-1.odt").model_dump()
    assert result["edited"] is False
    assert result["preview_pdf_key"] is None


def test_edit_document_starts_from_the_previous_draft_when_adjusting(fake_io):
    tasks.edit_document.apply(args=[_payload(previous_draft_key="drafts/doc-1/job-0.odt")], task_id="job-2").get()

    fake_io.get_object.assert_called_once_with("drafts/doc-1/job-0.odt")


def test_edit_document_uses_the_markdown_media_type_and_extension(fake_io):
    tasks.edit_document.apply(args=[_payload(format="md")], task_id="job-3").get()

    key, _ = fake_io.put_object.call_args.args
    assert key == "drafts/doc-1/job-3.md"
    assert fake_io.put_object.call_args.kwargs["content_type"].startswith("text/markdown")


def test_edit_document_reports_its_logs_back_even_on_failure(fake_io):
    fake_io.get_object.side_effect = RuntimeError("storage down")

    outcome = tasks.edit_document.apply(args=[_payload()], task_id="job-4")

    assert outcome.failed()
    task_logging.backend_client.set_task_logs.assert_called_once()
    assert task_logging.backend_client.set_task_logs.call_args.args[0] == "job-4"
    assert "document doc-1" in task_logging.backend_client.set_task_logs.call_args.args[1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"prompt": ""},
        {"base_revision": 0},
        {"format": "pdf"},
        {"source_storage_key": None},
    ],
)
def test_the_input_contract_rejects_an_invalid_payload(overrides):
    with pytest.raises(ValidationError):
        EditJobInput.model_validate(_payload(**overrides))


def test_edit_document_with_an_invalid_payload_fails_without_touching_storage(fake_io):
    outcome = tasks.edit_document.apply(args=[_payload(prompt="")], task_id="job-5")

    assert outcome.failed()
    fake_io.get_object.assert_not_called()
    fake_io.put_object.assert_not_called()
