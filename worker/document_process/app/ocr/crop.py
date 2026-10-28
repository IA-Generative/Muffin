"""A region of a page, cropped when it is wanted (#409): nothing is stored. The page's image and the region's box
between 0 and 1 are all it takes; the tables (#410) and the descriptions of images (#411) crop theirs this way."""

import io

from PIL import Image

from app.ocr.contracts import Box

# A little of the page around the region, or the edge of a glyph or of a rule is lost; and a region smaller than
# MIN_SIDE_PIXELS is widened to it - a crop too small for a model to read anything in is no crop.
MARGIN_PIXELS = 8
MIN_SIDE_PIXELS = 32


def _span(low: float, high: float, size: int, margin: int, minimum: int) -> tuple[int, int]:
    """One side of the crop, in pixels: the region and its margin, cut at the page's edge; widened to the floor, around
    its middle and moved back onto the page, when that is too little to read anything in."""
    start, end = max(round(low * size) - margin, 0), min(round(high * size) + margin, size)
    if end - start < minimum:
        floor = min(minimum, size)
        middle = (start + end) / 2
        start, end = round(middle - floor / 2), round(middle + floor / 2)
        if start < 0:
            start, end = 0, floor
        elif end > size:
            start, end = size - floor, size
    return start, max(end, start + 1)


def crop_region(page_png: bytes, box: Box, margin: int = MARGIN_PIXELS, minimum: int = MIN_SIDE_PIXELS) -> bytes:
    """The PNG of the region of the page's PNG that `box` frames."""
    with Image.open(io.BytesIO(page_png)) as page:
        width, height = page.size
        left, right = _span(box.x_min, box.x_max, width, margin, minimum)
        top, bottom = _span(box.y_min, box.y_max, height, margin, minimum)
        out = io.BytesIO()
        page.crop((left, top, right, bottom)).save(out, format="PNG")
        return out.getvalue()
