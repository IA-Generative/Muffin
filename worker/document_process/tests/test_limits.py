"""What bounds a task (#294): nothing is killed for being big, only what does not come back."""

import pytest
from liteparse import ParseTimeoutError

from app import parsing, scraping, storage
from app.celery_app import celery_app
from app.config import settings


def test_no_task_has_a_hard_time_limit():
    assert celery_app.conf.task_time_limit is None
    assert all(task.time_limit is None for name, task in celery_app.tasks.items() if name.startswith("app.tasks."))


def test_every_task_has_a_soft_limit_as_a_safety_net():
    assert celery_app.conf.task_soft_time_limit == settings.TASK_SOFT_TIME_LIMIT_SECONDS


def test_the_broker_does_not_hand_a_running_task_to_another_worker():
    """Tasks are acknowledged when they end: past the visibility timeout, Redis gives one to a second
    worker. It must exceed every limit a task can run up to, soft limits included."""
    visibility = celery_app.conf.broker_transport_options["visibility_timeout"]
    longest = max(
        settings.TASK_SOFT_TIME_LIMIT_SECONDS,
        settings.IMPORT_SOFT_TIME_LIMIT_SECONDS,
        settings.REBUILD_SLICE_SECONDS,
        settings.OCR_PARSE_TIMEOUT_SECONDS,
    )
    assert visibility == settings.BROKER_VISIBILITY_TIMEOUT_SECONDS
    assert visibility > longest


def test_a_slice_of_a_rebuild_fits_in_the_visibility_timeout_with_room_to_spare():
    assert settings.REBUILD_SLICE_SECONDS + 3600 <= settings.BROKER_VISIBILITY_TIMEOUT_SECONDS


def _minimal_pdf() -> bytes:
    """A valid one-page PDF (a parser that rejects the file would fail before the deadline)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length 44 >>\nstream\nBT /F1 18 Tf 20 100 Td (Bonjour) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return body + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


class TestParsing:
    @pytest.fixture(autouse=True)
    def _fresh_parser(self, monkeypatch):
        monkeypatch.setattr(parsing, "_parser", None)

    def test_the_parser_runs_in_its_own_process_with_a_deadline(self, monkeypatch):
        made = []
        monkeypatch.setattr(parsing, "LiteParse", lambda **options: made.append(options) or object())

        parsing._get_parser()

        assert made[0]["pool_size"] == 1
        assert made[0]["parse_timeout"] == settings.OCR_PARSE_TIMEOUT_SECONDS

    def test_one_parser_per_process(self, monkeypatch):
        made = []
        monkeypatch.setattr(parsing, "LiteParse", lambda **options: made.append(options) or object())

        assert parsing._get_parser() is parsing._get_parser()
        assert len(made) == 1

    def test_a_document_that_hangs_the_parser_fails_instead_of_holding_the_slot(self, monkeypatch):
        """With a real parser: past the deadline its process is killed, and a fresh one takes over."""
        monkeypatch.setattr(settings, "OCR_PARSE_TIMEOUT_SECONDS", 0.001)
        parser = None
        try:
            parser = parsing._get_parser()
            with pytest.raises(ParseTimeoutError):
                parsing.parse_file(_minimal_pdf())
            # Same parser afterwards, with a sensible deadline: the killed process was replaced.
            parser._pool._timeout = 60
            assert parsing.parse_file(_minimal_pdf()).pages[0].text.strip() == "Bonjour"
        finally:
            if parser is not None:
                parser.close()


def test_the_storage_client_has_explicit_timeouts_and_a_few_retries():
    config = storage.RustFsStorage()._client.meta.config
    assert config.connect_timeout == settings.STORAGE_CONNECT_TIMEOUT_SECONDS
    assert config.read_timeout == settings.STORAGE_READ_TIMEOUT_SECONDS
    # 3 retries after the first attempt (botocore counts them as total_max_attempts).
    assert config.retries == {"mode": "standard", "total_max_attempts": 4}


def test_a_url_is_fetched_with_a_short_connect_and_a_long_download_timeout(monkeypatch):
    seen = {}

    def get(url, **options):
        seen.update(options)
        raise TimeoutError

    monkeypatch.setattr(scraping.Fetcher, "get", get)

    with pytest.raises(TimeoutError):
        scraping.fetch_url("https://example.com/big.pdf")

    connect, download = seen["timeout"]
    assert connect == settings.URL_FETCH_CONNECT_TIMEOUT_SECONDS <= 30
    assert download == settings.URL_FETCH_TIMEOUT_SECONDS >= 30 * 60
