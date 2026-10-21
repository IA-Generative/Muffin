from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.celery_app import celery_app
from app.config import settings
from app.scraping import content_hash

URL_DOCUMENT = {"id": "doc-1", "type": "url", "name": "https://example.com/page", "collection_id": "col-1"}


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", fake)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    return fake


# -- the hash of a page -------------------------------------------------------------------------


def test_the_hash_ignores_layout_noise_but_not_a_change_of_text():
    page = "# Titre\n\nPremier paragraphe.\n\nSecond paragraphe."

    assert content_hash(page) == content_hash("  # Titre  \n\n\n\nPremier paragraphe.   \n\nSecond paragraphe.\n\n")
    assert content_hash(page) != content_hash(page.replace("Second", "Deuxième"))
    assert len(content_hash(page)) == 64


def test_indexing_a_url_records_the_hash_of_what_was_indexed(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    monkeypatch.setattr(tasks._shared, "fetch_url_markdown", lambda url: "# Hello\n\nSome content")
    backend.get_document.return_value = {**URL_DOCUMENT, "storage_key": None}

    tasks.process_document("doc-1")

    backend.set_content_hash.assert_called_once_with("doc-1", content_hash("# Hello\n\nSome content"))


# -- the scan -----------------------------------------------------------------------------------


def test_the_scan_sends_one_refresh_per_document_the_backend_hands_out(backend, monkeypatch):
    sent = MagicMock()
    monkeypatch.setattr(tasks.refresh_url_document, "apply_async", sent)
    backend.claim_url_refresh.return_value = ["doc-1", "doc-2"]

    count = tasks.scan_url_refresh()

    assert count == 2
    assert [call.kwargs["args"] for call in sent.call_args_list] == [["doc-1"], ["doc-2"]]


def test_a_scan_with_nothing_due_sends_nothing(backend, monkeypatch):
    sent = MagicMock()
    monkeypatch.setattr(tasks.refresh_url_document, "apply_async", sent)
    backend.claim_url_refresh.return_value = []

    assert tasks.scan_url_refresh() == 0
    sent.assert_not_called()


def test_the_beat_runs_the_scan_on_the_configured_interval():
    entry = celery_app.conf.beat_schedule["scan-url-refresh"]

    assert entry["task"] == "app.tasks.scan_url_refresh"
    assert entry["schedule"] == settings.URL_REFRESH_SCAN_SECONDS == 30 * 60


# -- refreshing one document --------------------------------------------------------------------


def test_a_refreshed_page_is_reported_with_its_hash(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "fetch_url_markdown", lambda url: "# Page\n\nNouveau contenu")
    backend.get_document.return_value = URL_DOCUMENT
    backend.report_url_fetch.return_value = True

    changed = tasks.refresh_url_document("doc-1")

    assert changed is True
    backend.report_url_fetch.assert_called_once_with("doc-1", content_hash("# Page\n\nNouveau contenu"))
    # Reprocessing is the backend's call, never this task's: it doesn't write anything itself.
    backend.add_page.assert_not_called()
    backend.update_status.assert_not_called()


def test_a_page_that_cannot_be_fetched_changes_nothing(backend, monkeypatch):
    def unreachable(url):
        raise TimeoutError("site down")

    monkeypatch.setattr(tasks._shared, "fetch_url_markdown", unreachable)
    backend.get_document.return_value = URL_DOCUMENT

    assert tasks.refresh_url_document("doc-1") is False
    backend.report_url_fetch.assert_not_called()


def test_a_document_that_is_not_a_url_is_left_alone(backend, monkeypatch):
    fetch = MagicMock()
    monkeypatch.setattr(tasks._shared, "fetch_url_markdown", fetch)
    backend.get_document.return_value = {**URL_DOCUMENT, "type": "file"}

    assert tasks.refresh_url_document("doc-1") is False
    fetch.assert_not_called()
