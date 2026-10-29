"""The layout of a scanned page kept by the backend (#409): sent with the page, and cropped when it is wanted."""

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app import reuse, task_logging, tasks
from app.config import settings
from app.ocr.contracts import Box, PageLayout, Region, RegionType
from app.ocr.crop import crop_region
from app.ocr.regions import MAX_REGIONS, regions_of


def _region(order, type_, box=(0.1, 0.1, 0.5, 0.2), **extra) -> Region:
    x0, y0, x1, y1 = box
    return Region(
        type=type_,
        score=0.9,
        reading_order=order,
        box=Box(x_min=x0, y_min=y0, x_max=x1, y_max=y1),
        **extra,
    )


def _layout(*regions) -> PageLayout:
    return PageLayout(
        document_id="d", page_number=1, width_px=1000, height_px=1000, regions=list(regions), model_version="l"
    )


# --- the regions the backend is sent ---


def test_every_region_is_sent_in_reading_order_the_running_headers_too():
    layout = _layout(
        _region(0, RegionType.HEADER),
        _region(1, RegionType.TITLE, title_level=1),
        _region(2, RegionType.TEXT, polygon=[(0.1, 0.1), (0.5, 0.1), (0.5, 0.2)]),
        _region(3, RegionType.TABLE),
        _region(4, RegionType.IMAGE),
        _region(5, RegionType.FOOTER),
        _region(6, RegionType.PAGE_NUMBER),
    )
    sent = regions_of(layout)
    assert [region["type"] for region in sent] == ["header", "title", "text", "table", "image", "footer", "page_number"]
    assert sent[1]["title_level"] == 1 and sent[0]["title_level"] is None


def test_a_region_is_sent_with_its_score_its_box_and_its_outline():
    [region] = regions_of(_layout(_region(0, RegionType.TEXT, (0.2, 0.3, 0.6, 0.4), polygon=[(0.2, 0.3), (0.6, 0.4)])))
    assert region == {
        "type": "text",
        "score": 0.9,
        "x_min": 0.2,
        "y_min": 0.3,
        "x_max": 0.6,
        "y_max": 0.4,
        "polygon": [[0.2, 0.3], [0.6, 0.4]],
        "title_level": None,
        "caption": None,
        "caption_model": None,
    }


def test_a_region_without_outline_has_none():
    assert regions_of(_layout(_region(0, RegionType.TEXT)))[0]["polygon"] is None


def test_a_page_with_no_region_sends_none():
    assert regions_of(_layout()) == []


def test_no_more_regions_are_sent_than_the_backend_takes():
    layout = _layout(*(_region(order, RegionType.TEXT) for order in range(MAX_REGIONS + 20)))
    assert len(regions_of(layout)) == MAX_REGIONS


# --- sent with the page ---

DOCUMENT = {
    "id": "doc-1",
    "type": "file",
    "name": "scan.pdf",
    "storage_key": "docs/scan.pdf",
    "collection_id": "col-1",
}


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    storage = MagicMock()
    storage.get_object.return_value = b"%PDF-1.4 a scan"
    monkeypatch.setattr(tasks._shared, "storage", storage)
    backend.get_document.return_value = DOCUMENT
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 2)
    return backend


def _page(number, **extra):
    return SimpleNamespace(page_num=number, text=f"p{number}", text_items=[], width=600, height=800, **extra)


def test_a_page_read_by_the_pods_is_written_with_its_layout(backend, monkeypatch):
    sent = regions_of(_layout(_region(0, RegionType.TITLE, title_level=1), _region(1, RegionType.IMAGE)))
    result = SimpleNamespace(pages=[_page(1, layout_regions=sent), _page(2)], screenshots=[])
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=result))
    monkeypatch.setattr(tasks._shared, "read_scanned_pages", lambda document_id, data, parsed: parsed)

    tasks.process_document("doc-1")

    calls = {call.kwargs["page_number"]: call.kwargs for call in backend.add_page.call_args_list}
    assert [region["type"] for region in calls[1]["regions"]] == ["title", "image"]
    # A page read another way has no layout, and says so: what a former extraction left is cleared.
    assert calls[2]["regions"] == []


def test_the_default_engine_sends_every_page_without_layout(backend, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    result = SimpleNamespace(pages=[_page(1), _page(2)], screenshots=[])
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=result))

    tasks.process_document("doc-1")

    assert [call.kwargs["regions"] for call in backend.add_page.call_args_list] == [[], []]


def test_the_client_sends_the_regions_only_when_it_has_them(monkeypatch):
    from app.backend_client import BackendClient

    client = BackendClient()
    posted = []
    client._client = MagicMock()
    client._client.post.side_effect = lambda url, json: posted.append(json) or MagicMock()

    client.add_page("d", 1, "text")
    client.add_page("d", 2, "text", regions=[])
    client.add_page("d", 3, "text", regions=[{"type": "text"}])

    assert "regions" not in posted[0]
    assert posted[1]["regions"] == [] and posted[2]["regions"] == [{"type": "text"}]


# --- the fingerprint (#300) ---


def test_the_layout_is_part_of_what_an_extraction_by_the_pods_is(monkeypatch):
    """An extraction made before the layout was kept has none: it must not be reused as if it had."""
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    assert reuse._ocr_pods()["regions"] == 1


# --- cropped when it is wanted ---


def _png(width=1000, height=2000) -> bytes:
    page = Image.new("RGB", (width, height), "white")
    # A red block where the region is, a blue one elsewhere.
    for x in range(200, 600):
        for y in range(400, 600):
            page.putpixel((x, y), (255, 0, 0))
    for x in range(700, 800):
        for y in range(1500, 1600):
            page.putpixel((x, y), (0, 0, 255))
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    return buffer.getvalue()


def _size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as image:
        return image.size


def test_a_region_is_cropped_from_the_page_with_a_little_around_it():
    box = Box(x_min=0.2, y_min=0.2, x_max=0.6, y_max=0.3)
    out = crop_region(_png(), box, margin=8, minimum=32)
    # 400 x 200 pixels, 8 more on each side.
    assert _size(out) == (416, 216)
    with Image.open(io.BytesIO(out)) as image:
        assert image.getpixel((100, 100)) == (255, 0, 0)
        assert image.getpixel((2, 2)) == (255, 255, 255)


def test_a_crop_does_not_go_past_the_page():
    box = Box(x_min=0.0, y_min=0.0, x_max=0.3, y_max=0.1)
    assert _size(crop_region(_png(), box, margin=8, minimum=32)) == (308, 208)
    box = Box(x_min=0.8, y_min=0.9, x_max=1.0, y_max=1.0)
    assert _size(crop_region(_png(), box, margin=8, minimum=32)) == (208, 208)


def test_a_region_too_small_is_widened_to_the_floor_not_past_the_page():
    box = Box(x_min=0.5, y_min=0.5, x_max=0.5, y_max=0.5)
    assert _size(crop_region(_png(), box, margin=0, minimum=32)) == (32, 32)
    corner = Box(x_min=0.0, y_min=0.0, x_max=0.0, y_max=0.0)
    assert _size(crop_region(_png(), corner, margin=0, minimum=32)) == (32, 32)


def test_the_crop_is_the_region_asked_for_and_not_another():
    blue = Box(x_min=0.7, y_min=0.75, x_max=0.8, y_max=0.8)
    with Image.open(io.BytesIO(crop_region(_png(), blue, margin=0, minimum=32))) as image:
        assert image.getpixel((50, 50)) == (0, 0, 255)


def test_a_page_smaller_than_the_floor_gives_the_page():
    tiny = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(tiny, format="PNG")
    assert _size(crop_region(tiny.getvalue(), Box(x_min=0, y_min=0, x_max=1, y_max=1), margin=0, minimum=32)) == (
        20,
        10,
    )
