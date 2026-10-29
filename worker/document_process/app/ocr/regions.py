"""The layout of a scanned page, as the backend keeps it (#409): `page_regions`, one row per region, in reading order.

Every region the layout pod found is sent - the running headers, footers and page numbers too - with its type, its
score and its box between 0 and 1. Only the markdown of the page leaves some out. No crop is made nor stored: a region
is cropped from the page's image when something wants it (app/ocr/crop.py)."""

from typing import Any

from app.ocr.contracts import PageLayout

# What the backend accepts for a page (schemas/internal_document.py): beyond this, the page is cut, not refused.
MAX_REGIONS = 500


def regions_of(layout: PageLayout, captions: dict[int, tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    """The layout's regions in the shape of the backend's `RegionIn`, in reading order. `captions`: the description of
    a region (#411) by its reading order, with the model that wrote it."""
    described = captions or {}
    return [
        {
            "type": region.type.value,
            "score": region.score,
            "x_min": region.box.x_min,
            "y_min": region.box.y_min,
            "x_max": region.box.x_max,
            "y_max": region.box.y_max,
            "polygon": [[x, y] for x, y in region.polygon] if region.polygon else None,
            "title_level": region.title_level,
            "caption": described[region.reading_order][0] if region.reading_order in described else None,
            "caption_model": described[region.reading_order][1] if region.reading_order in described else None,
        }
        for region in layout.regions[:MAX_REGIONS]
    ]
