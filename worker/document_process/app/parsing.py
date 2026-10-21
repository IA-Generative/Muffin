import threading

from liteparse import LiteParse
from liteparse.types import ParseResult

from app.config import settings

_parser: LiteParse | None = None
_parser_lock = threading.Lock()


def _get_parser() -> LiteParse:
    """One parser per process, made on first use - in the Celery child process, not before the fork.
    It parses in a process of its own with a deadline (#294): a document that hangs the parser is
    killed there after OCR_PARSE_TIMEOUT_SECONDS and replaced by a fresh one, while the task - and the
    worker's slot - carries on and fails the document with a clear error."""
    global _parser
    with _parser_lock:
        if _parser is None:
            _parser = LiteParse(
                output_format="json",
                ocr_enabled=True,
                ocr_language=settings.OCR_LANGUAGE,
                tessdata_path=settings.TESSDATA_PATH,
                extract_blocks=True,
                extract_screenshots=True,
                pool_size=1,
                parse_timeout=settings.OCR_PARSE_TIMEOUT_SECONDS,
            )
        return _parser


def parse_file(data: bytes) -> ParseResult:
    """Extract text, layout blocks (with bbox) and page screenshots from a
    PDF/Office/image file. French Tesseract OCR by default for scanned pages.
    Raises liteparse's ParseTimeoutError past the deadline."""
    return _get_parser().parse(data)
