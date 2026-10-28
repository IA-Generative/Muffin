import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import scraping, task_logging, tasks
from app.celery_app import celery_app
from app.scraping import FetchedUrl, UnsupportedUrlContentError, content_hash

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
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: FetchedUrl(markdown="# Hello\n\nSome content"))
    backend.get_document.return_value = {**URL_DOCUMENT, "storage_key": None}

    tasks.process_document("doc-1")

    backend.set_content_hash.assert_called_once_with("doc-1", content_hash("# Hello\n\nSome content"))


# -- a URL serving a file ----------------------------------------------------------------------


def _served(monkeypatch, content_type, body, markdown="# Page"):
    page = MagicMock(status=200, headers={"Content-Type": content_type} if content_type else {}, body=body)
    page.markdown.return_value = markdown
    monkeypatch.setattr(scraping.Fetcher, "get", lambda url, **options: page)


def test_an_html_page_is_rendered_to_markdown(monkeypatch):
    _served(monkeypatch, "text/html; charset=utf-8", b"<html><body>Page</body></html>")

    fetched = scraping.fetch_url("https://example.com/article")

    assert (fetched.markdown, fetched.data) == ("# Page", None)
    assert fetched.content_hash == content_hash("# Page")


@pytest.mark.parametrize(
    ("url", "content_type", "body", "filename"),
    [
        ("https://example.com/files/Rapport%20annuel.pdf", "application/pdf", b"%PDF-1.4 ...", "Rapport_annuel.pdf"),
        # A PDF sent as an anonymous binary, from a URL without an extension: its signature tells.
        ("https://example.com/download?id=3", "application/octet-stream", b"%PDF-1.7 ...", "download.pdf"),
        ("https://example.com/data/export", "text/csv", b"a,b\n1,2\n", "export.csv"),
        ("https://example.com/notes.md", "text/plain", b"# Notes", "notes.md"),
        (
            "https://example.com/doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK...",
            "doc.docx",
        ),
        ("https://example.com/scan", "image/jpeg", b"\xff\xd8", "scan.jpg"),
    ],
)
def test_a_file_is_downloaded_and_named_after_its_format(monkeypatch, url, content_type, body, filename):
    _served(monkeypatch, content_type, body)

    fetched = scraping.fetch_url(url)

    assert (fetched.data, fetched.filename) == (body, filename)
    # Compared byte for byte at the next refresh check.
    assert fetched.content_hash == hashlib.sha256(body).hexdigest()


def test_a_format_the_pipeline_cannot_process_is_refused(monkeypatch):
    _served(monkeypatch, "application/zip", b"PK...")

    with pytest.raises(UnsupportedUrlContentError):
        scraping.fetch_url("https://example.com/archive")


def test_a_url_serving_a_file_is_stored_and_processed_like_an_upload(backend, monkeypatch):
    spawn, storage = MagicMock(), MagicMock()
    monkeypatch.setattr(tasks._shared, "_spawn", spawn)
    monkeypatch.setattr(tasks._shared, "storage", storage)
    pdf = FetchedUrl(data=b"%PDF-1.4", filename="rapport.pdf", content_type="application/pdf")
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: pdf)
    storage.get_object.return_value = pdf.data
    parse = MagicMock(return_value=SimpleNamespace(pages=[SimpleNamespace(page_num=1, text="Texte")], screenshots=[]))
    monkeypatch.setattr(tasks._shared, "parse_file", parse)
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 1)
    backend.get_document.return_value = {**URL_DOCUMENT, "storage_key": None}

    tasks.process_document("doc-1")

    key = "documents/col-1/doc-1-rapport.pdf"
    storage.put_object.assert_called_once_with(key, b"%PDF-1.4", content_type="application/pdf")
    backend.set_content_hash.assert_called_once_with("doc-1", pdf.content_hash, storage_key=key)
    parse.assert_called_once_with(b"%PDF-1.4")
    backend.add_page.assert_called_once_with(
        "doc-1", page_number=1, content="Texte", screenshot=None, text_boxes=[], regions=[]
    )
    assert spawn.call_args.args[2] == "app.tasks.chunk_document"


def test_a_url_serving_a_table_goes_through_the_tabular_branch(backend, monkeypatch):
    spawn = MagicMock()
    monkeypatch.setattr(tasks._shared, "_spawn", spawn)
    monkeypatch.setattr(tasks._shared, "storage", MagicMock())
    monkeypatch.setattr(
        tasks._shared,
        "fetch_url",
        lambda url: FetchedUrl(data=b"a,b\n1,2", filename="export.csv", content_type="text/csv"),
    )
    backend.get_document.return_value = {**URL_DOCUMENT, "storage_key": None}

    tasks.process_document("doc-1")

    assert spawn.call_args.args[2] == "app.tasks.process_tabular_document"
    assert spawn.call_args.args[1] == ["doc-1", "col-1", "csv"]


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


def test_the_beat_runs_the_scan_on_the_hour_and_at_half_past():
    entry = celery_app.conf.beat_schedule["scan-url-refresh"]

    assert entry["task"] == "app.tasks.scan_url_refresh"
    # Aligned on the clock, not every 30 minutes from the worker's start: a refresh set for 14:30
    # runs at 14:30.
    assert entry["schedule"].minute == {0, 30}


# -- refreshing one document --------------------------------------------------------------------


def test_a_refreshed_page_is_reported_with_its_hash(backend, monkeypatch):
    monkeypatch.setattr(tasks._shared, "fetch_url", lambda url: FetchedUrl(markdown="# Page\n\nNouveau contenu"))
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

    monkeypatch.setattr(tasks._shared, "fetch_url", unreachable)
    backend.get_document.return_value = URL_DOCUMENT

    assert tasks.refresh_url_document("doc-1") is False
    backend.report_url_fetch.assert_not_called()


def test_a_document_that_is_not_a_url_is_left_alone(backend, monkeypatch):
    fetch = MagicMock()
    monkeypatch.setattr(tasks._shared, "fetch_url", fetch)
    backend.get_document.return_value = {**URL_DOCUMENT, "type": "file"}

    assert tasks.refresh_url_document("doc-1") is False
    fetch.assert_not_called()


# -- what isn't the page ---------------------------------------------------------------------------


def _answer(monkeypatch, status, body=b"", headers=None):
    page = MagicMock(status=status, headers=headers or {"Content-Type": "text/html"}, body=body)
    page.markdown.return_value = "# Not the page"
    monkeypatch.setattr(scraping.Fetcher, "get", lambda url, **options: page)


def test_an_anti_bot_challenge_is_refused_rather_than_indexed(monkeypatch):
    _answer(monkeypatch, 403, b"<!DOCTYPE html><html><head><title>Just a moment...</title>")

    with pytest.raises(scraping.UrlFetchError, match="contre les robots"):
        scraping.fetch_url("https://www.legifrance.gouv.fr/download/file/pdf/LEGITEXT.pdf/LEGI")


def test_a_challenge_cloudflare_flags_is_refused_whatever_its_title(monkeypatch):
    _answer(monkeypatch, 403, b"<html></html>", {"Content-Type": "text/html", "cf-mitigated": "challenge"})

    with pytest.raises(scraping.UrlFetchError, match="contre les robots"):
        scraping.fetch_url("https://example.com/doc.pdf")


@pytest.mark.parametrize("status", [404, 500])
def test_an_http_error_is_refused_rather_than_indexed(monkeypatch, status):
    _answer(monkeypatch, status, b"<html><title>Not Found</title></html>")

    with pytest.raises(scraping.UrlFetchError, match=f"répondu {status}"):
        scraping.fetch_url("https://example.com/gone")
