from liteparse import LiteParse
from liteparse.types import ParseResult

from app.config import settings


def parse_file(data: bytes) -> ParseResult:
    """Extract text, layout blocks (with bbox) and page screenshots from a
    PDF/Office/image file. French Tesseract OCR by default for scanned pages."""
    parser = LiteParse(
        output_format="json",
        ocr_enabled=True,
        ocr_language=settings.OCR_LANGUAGE,
        tessdata_path=settings.TESSDATA_PATH,
        extract_blocks=True,
        extract_screenshots=True,
    )
    return parser.parse(data)
