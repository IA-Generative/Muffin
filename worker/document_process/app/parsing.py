import threading

from liteparse import LiteParse
from liteparse.types import ParseResult

from app.config import settings

_parser: LiteParse | None = None
_parser_lock = threading.Lock()


def _make_parser(**options) -> LiteParse:
    """It parses in a process of its own with a deadline (#294): a document that hangs the parser is
    killed there after OCR_PARSE_TIMEOUT_SECONDS and replaced by a fresh one, while the task - and the
    worker's slot - carries on and fails the document with a clear error."""
    return LiteParse(
        **{
            "output_format": "json",
            "ocr_enabled": True,
            "ocr_language": settings.OCR_LANGUAGE,
            "tessdata_path": settings.TESSDATA_PATH,
            "extract_blocks": True,
            "extract_screenshots": True,
            "pool_size": 1,
            "parse_timeout": settings.OCR_PARSE_TIMEOUT_SECONDS,
            **options,
        }
    )


def _get_parser() -> LiteParse:
    """One parser per process, made on first use - in the Celery child process, not before the fork."""
    global _parser
    with _parser_lock:
        if _parser is None:
            _parser = _make_parser()
        return _parser


def parse_file(data: bytes) -> ParseResult:
    """Extract text, layout blocks (with bbox) and page screenshots from a
    PDF/Office/image file. French Tesseract OCR by default for scanned pages.
    Raises liteparse's ParseTimeoutError past the deadline."""
    return _get_parser().parse(data)


def count_pages(data: bytes) -> int:
    """The number of pages of a PDF, without the OCR nor the screenshots: the first page only is read."""
    parser = _make_parser(ocr_enabled=False, extract_blocks=False, extract_screenshots=False, max_pages=1)
    try:
        return parser.parse(data).total_pages
    finally:
        parser.close()


def parse_pages(data: bytes, first: int, last: int) -> ParseResult:
    """`parse_file` of the pages first..last (1-based, inclusive) only. A parser of its own, as which pages
    it reads is part of its options: its process starts and ends with the range, and so does its deadline."""
    parser = _make_parser(target_pages=f"{first}-{last}")
    try:
        return parser.parse(data)
    finally:
        parser.close()
