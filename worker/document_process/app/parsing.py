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
            # With the OCR pods (OCR_ENGINE=layout) liteparse does not run Tesseract itself - app/ocr/scanned.py
            # sends the pages it says need an OCR to the pods - and says per page whether one is needed.
            "ocr_enabled": settings.OCR_ENGINE == "tesseract",
            "include_complexity": settings.OCR_ENGINE == "layout",
            "ocr_language": settings.OCR_LANGUAGE,
            "tessdata_path": settings.TESSDATA_PATH,
            "extract_blocks": True,
            "extract_screenshots": True,
            # The words of each line, with their boxes: what frames a passage word by word (#350).
            "emit_word_boxes": True,
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


def _page_list(page_numbers: list[int]) -> str:
    """The pages as liteparse's target_pages writes them: "1,3-5"."""
    ordered = sorted(set(page_numbers))
    parts, start = [], 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1] == ordered[end] + 1:
            end += 1
        parts.append(str(ordered[start]) if start == end else f"{ordered[start]}-{ordered[end]}")
        start = end + 1
    return ",".join(parts)


def render_pages(data: bytes, page_numbers: list[int]) -> dict[int, tuple[bytes, int, int]]:
    """The image of the given pages (PNG, width, height) at OCR_PAGE_DPI - what the OCR pods read."""
    parser = _make_parser(
        ocr_enabled=False,
        include_complexity=False,
        extract_blocks=False,
        emit_word_boxes=False,
        dpi=settings.OCR_PAGE_DPI,
        target_pages=_page_list(page_numbers),
    )
    try:
        return {s.page_num: (s.image_bytes, s.width, s.height) for s in parser.parse(data).screenshots}
    finally:
        parser.close()


def tesseract_pages(data: bytes, page_numbers: list[int]) -> ParseResult:
    """The given pages read by liteparse's own OCR - the page that the OCR pods could not read."""
    parser = _make_parser(ocr_enabled=True, include_complexity=False, target_pages=_page_list(page_numbers))
    try:
        return parser.parse(data)
    finally:
        parser.close()
