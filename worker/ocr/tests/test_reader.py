"""The ocr pod: the crops, the words, the lines of the contract (app/reader.py) and the task around them."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app import reader as reader_module
from app.config import settings
from app.contracts import Box, PageText, Region, RegionType
from app.reader import TextReader, build_words, crop_region, lines_of

WIDTH, HEIGHT = 1000, 2000


def _region(order, type_, box) -> Region:
    x0, y0, x1, y1 = box
    return Region(type=type_, score=0.9, reading_order=order, box=Box(x_min=x0, y_min=y0, x_max=x1, y_max=y1))


@pytest.fixture(autouse=True)
def _no_border_by_default(monkeypatch):
    """Most tests are about where things land: the border has tests of its own."""
    monkeypatch.setattr(settings, "OCR_CROP_BORDER_PIXELS", 0)
    monkeypatch.setattr(settings, "OCR_REGION_PADDING_PIXELS", 0)


def _page(value=0) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)


# --- the crops ---


def test_a_crop_is_the_region_of_the_page_and_says_where_it_is():
    crop, x_offset, y_offset = crop_region(_page(), _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2)), [])
    assert crop.shape == (200, 400, 3)
    assert (x_offset, y_offset) == (100, 200)


def test_a_crop_is_a_copy_the_page_is_never_painted():
    page = _page(0)
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    crop_region(page, text, [_region(1, RegionType.IMAGE, (0.1, 0.1, 0.5, 0.2))])
    assert page.max() == 0


def test_the_regions_that_are_not_text_are_painted_white_in_the_crop():
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    table = _region(1, RegionType.TABLE, (0.3, 0.15, 0.6, 0.3))
    crop, _, _ = crop_region(_page(0), text, [table])
    # The table covers the lower right of the crop: x from 300 to 500, y from 300 to 400 of the page.
    assert crop[150:, 200:].min() == 255
    assert crop[:100, :].max() == 0 and crop[:, :200].max() == 0


@pytest.mark.parametrize(
    "type_",
    [
        RegionType.TABLE,
        RegionType.IMAGE,
        RegionType.FORMULA,
        RegionType.LOGO,
        RegionType.STAMP,
        RegionType.HEADER,
        RegionType.FOOTER,
        RegionType.PAGE_NUMBER,
    ],
)
def test_each_kind_of_region_that_is_not_text_is_masked(type_):
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    crop, _, _ = crop_region(_page(0), text, [_region(1, type_, (0.1, 0.1, 0.5, 0.2))])
    assert crop.min() == 255


def test_a_formula_inside_a_line_is_not_painted_it_would_cut_the_sentence():
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    crop, _, _ = crop_region(_page(0), text, [_region(1, RegionType.OTHER, (0.2, 0.12, 0.3, 0.14))])
    assert crop.max() == 0


def test_another_text_region_is_not_painted():
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    crop, _, _ = crop_region(_page(0), text, [_region(1, RegionType.TEXT, (0.3, 0.15, 0.6, 0.3))])
    assert crop.max() == 0


def test_a_region_that_only_touches_the_crop_does_not_paint_it():
    text = _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))
    below = _region(1, RegionType.TABLE, (0.1, 0.2, 0.5, 0.4))
    crop, _, _ = crop_region(_page(0), text, [below])
    assert crop.max() == 0


def test_the_crop_is_padded_without_going_past_the_page(monkeypatch):
    monkeypatch.setattr(settings, "OCR_REGION_PADDING_PIXELS", 8)
    crop, x_offset, y_offset = crop_region(_page(), _region(0, RegionType.TEXT, (0.0, 0.1, 0.5, 0.2)), [])
    assert (x_offset, y_offset) == (0, 192)
    assert crop.shape == (216, 508, 3)


def test_a_white_border_goes_around_the_crop_and_the_offset_says_so(monkeypatch):
    monkeypatch.setattr(settings, "OCR_CROP_BORDER_PIXELS", 32)
    crop, x_offset, y_offset = crop_region(_page(0), _region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2)), [])
    assert crop.shape == (200 + 64, 400 + 64, 3)
    assert crop[:32].min() == 255 and crop[:, :32].min() == 255
    assert crop[32:-32, 32:-32].max() == 0
    # The crop's top left corner is outside the region, by the border.
    assert (x_offset, y_offset) == (100 - 32, 200 - 32)


# --- the words ---


def _boxes(*spans):
    return [(a, 10.0, b, 30.0) for a, b in spans]


def test_the_words_of_a_line_take_the_union_of_the_pieces_that_cover_them():
    # PaddleOCR's pieces of "Où l'été": "O", "ù ", "l", "'", "é", "t", "é".
    segments = ["O", "ù ", "l", "'", "é", "t", "é"]
    boxes = _boxes((0, 10), (10, 25), (25, 30), (30, 34), (34, 44), (44, 52), (52, 62))
    words = build_words("Où l'été", segments, boxes, (0.0, 10.0, 62.0, 30.0))
    assert [word for word, _ in words] == ["Où", "l'été"]
    assert words[0][1] == (0, 10.0, 25, 30.0)
    assert words[1][1] == (25, 10.0, 62, 30.0)


def test_a_line_whose_pieces_do_not_make_its_text_is_cut_in_proportion_to_its_characters():
    words = build_words("ab cd", ["xx"], _boxes((0, 100)), (0.0, 0.0, 100.0, 20.0))
    assert [word for word, _ in words] == ["ab", "cd"]
    assert words[0][1] == (0.0, 0.0, 40.0, 20.0)
    assert words[1][1] == (60.0, 0.0, 100.0, 20.0)


def test_a_line_without_pieces_is_cut_in_proportion_too():
    words = build_words("abcd", None, None, (10.0, 0.0, 50.0, 20.0))
    assert words == [("abcd", (10.0, 0.0, 50.0, 20.0))]


def test_a_blank_line_has_no_word():
    assert build_words("   ", None, None, (0.0, 0.0, 10.0, 10.0)) == []


# --- the lines of the contract ---


def _result(texts, scores, boxes, segments=None, regions=None) -> dict:
    return {
        "rec_texts": texts,
        "rec_scores": scores,
        "rec_boxes": np.array(boxes),
        "text_word": segments or [],
        "text_word_region": regions or [],
    }


def test_the_lines_are_in_the_pages_frame_between_0_and_1():
    result = _result(["Bonjour monde"], [0.97], [[10, 20, 110, 40]])
    [line] = lines_of(result, x_offset=100, y_offset=200, width=WIDTH, height=HEIGHT)
    assert line.text == "Bonjour monde" and line.score == 0.97
    assert (line.box.x_min, line.box.y_min, line.box.x_max, line.box.y_max) == (0.11, 0.11, 0.21, 0.12)
    assert [word.text for word in line.words] == ["Bonjour", "monde"]
    assert all(0 <= word.box.x_min <= word.box.x_max <= 1 for word in line.words)


def test_a_line_in_the_border_is_cut_to_the_page_not_refused():
    result = _result(["x"], [0.9], [[0, 0, 50, 20]])
    [line] = lines_of(result, x_offset=-32, y_offset=-32, width=WIDTH, height=HEIGHT)
    assert line.box.x_min == 0.0 and line.box.y_min == 0.0


def test_an_empty_text_is_not_a_line():
    assert lines_of(_result([" ", ""], [0.9, 0.9], [[0, 0, 5, 5], [0, 0, 5, 5]]), 0, 0, WIDTH, HEIGHT) == []


def test_a_line_under_the_threshold_is_dropped_and_the_default_keeps_them_all(monkeypatch):
    result = _result(["bon", "mauvais"], [0.95, 0.2], [[0, 0, 5, 5], [0, 10, 5, 15]])
    assert len(lines_of(result, 0, 0, WIDTH, HEIGHT)) == 2
    monkeypatch.setattr(settings, "OCR_LINE_MIN_SCORE", 0.5)
    assert [line.text for line in lines_of(result, 0, 0, WIDTH, HEIGHT)] == ["bon"]


def test_a_crop_where_nothing_was_found_has_no_line():
    assert lines_of({"rec_texts": [], "rec_scores": [], "rec_boxes": np.empty((0, 4))}, 0, 0, WIDTH, HEIGHT) == []


# --- the reader ---


class FakeModel:
    """Reads, in each crop, one line of the crop's own size, and notes what it was given."""

    def __init__(self):
        self.crops = []

    def predict(self, crop, return_word_box=False):
        self.crops.append(crop)
        height, width = crop.shape[:2]
        return [_result([f"ligne {len(self.crops)}"], [0.9], [[0, 0, width, height]])]


def test_only_the_text_regions_are_read_each_from_its_crop():
    regions = [
        _region(0, RegionType.TITLE, (0.1, 0.05, 0.9, 0.1)),
        _region(1, RegionType.TEXT, (0.1, 0.15, 0.9, 0.3)),
        _region(2, RegionType.IMAGE, (0.1, 0.35, 0.5, 0.5)),
        _region(3, RegionType.TABLE, (0.1, 0.55, 0.9, 0.7)),
        _region(4, RegionType.CAPTION, (0.1, 0.5, 0.5, 0.53)),
    ]
    model = FakeModel()
    page = TextReader(lambda: model).read(_page(), regions, "doc-1", 3)
    assert isinstance(page, PageText)
    assert (page.document_id, page.page_number) == ("doc-1", 3)
    assert [region.region_order for region in page.regions] == [0, 1, 4]
    assert len(model.crops) == 3


def test_what_was_read_is_placed_on_the_page_not_on_the_crop():
    model = FakeModel()
    region = _region(0, RegionType.TEXT, (0.2, 0.1, 0.6, 0.2))
    page = TextReader(lambda: model).read(_page(), [region], "doc", 1)
    [line] = page.regions[0].lines
    assert (line.box.x_min, line.box.y_min, line.box.x_max, line.box.y_max) == (0.2, 0.1, 0.6, 0.2)


def test_a_page_without_text_region_is_a_valid_empty_text():
    page = TextReader(lambda: FakeModel()).read(_page(), [_region(0, RegionType.IMAGE, (0.1, 0.1, 0.5, 0.5))], "d", 1)
    assert page.regions == []
    assert PageText.model_validate_json(page.model_dump_json()) == page


def test_a_region_where_nothing_is_read_is_there_with_no_line():
    class Blind:
        def predict(self, crop, return_word_box=False):
            return []

    page = TextReader(lambda: Blind()).read(_page(), [_region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))], "d", 1)
    assert [(region.region_order, region.lines) for region in page.regions] == [(0, [])]


def test_the_models_are_loaded_once_for_many_pages_and_not_before_they_are_needed():
    loads = []

    def factory():
        loads.append(1)
        return FakeModel()

    reader = TextReader(factory)
    assert loads == []
    for number in (1, 2, 3):
        reader.read(_page(), [_region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2))], "doc", number)
    assert len(loads) == 1


def test_a_missing_model_fails_with_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODELS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="no OCR model"):
        reader_module._make_model()


# --- the task ---


def _png(width=120, height=80) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_task_reads_the_page_from_storage_and_gives_the_text_in_json(monkeypatch):
    from app import tasks

    asked, seen = [], {}

    class Storage:
        def get_object(self, key):
            asked.append(key)
            return _png(120, 80)

    class Reader:
        def read(self, image, regions, document_id, page_number):
            seen["shape"] = image.shape
            seen["first_pixel_bgr"] = image[0, 0].tolist()
            seen["types"] = [region.type for region in regions]
            return PageText(document_id=document_id, page_number=page_number, model_version="fake")

    monkeypatch.setattr(tasks, "storage", Storage())
    monkeypatch.setattr(tasks, "reader", Reader())
    layout_regions = [_region(0, RegionType.TEXT, (0.1, 0.1, 0.5, 0.2)).model_dump(mode="json")]
    result = tasks.ocr_regions("doc-1", 2, "ocr-pages/doc-1/page-2.png", layout_regions)
    assert asked == ["ocr-pages/doc-1/page-2.png"]
    # A BGR array, as OpenCV holds a page: the image's (10, 20, 30) RGB is (30, 20, 10) here.
    assert seen == {"shape": (80, 120, 3), "first_pixel_bgr": [30, 20, 10], "types": [RegionType.TEXT]}
    assert PageText.model_validate(result).page_number == 2


def test_the_task_refuses_regions_that_are_not_the_contracts():
    from app import tasks

    with pytest.raises(ValueError):
        tasks.ocr_regions("doc", 1, "key", [{"type": "text", "score": 5}])


def test_the_task_is_on_the_ocr_queue_under_the_name_the_extraction_worker_sends_to():
    from app.celery_app import celery_app

    assert "app.tasks.ocr_regions" in celery_app.tasks
    assert celery_app.conf.task_default_queue == settings.OCR_QUEUE_NAME == "document_ocr"
    [queue] = celery_app.conf.task_queues
    assert queue.exchange.name == queue.routing_key == queue.name == settings.OCR_QUEUE_NAME


# --- the real models: skipped where they are not (the image of the pod has them) ---

_ROOT = Path(os.environ.get("MODELS_DIR", settings.MODELS_DIR))
_HAVE_MODELS = all(
    (_ROOT / name / "inference.onnx").is_file() for name in (settings.OCR_DET_MODEL_NAME, settings.OCR_REC_MODEL_NAME)
)


@pytest.mark.slow
@pytest.mark.skipif(not _HAVE_MODELS, reason=f"no models in {_ROOT}")
def test_the_real_models_read_french_with_its_accents_in_a_region(monkeypatch):
    from PIL import ImageDraw, ImageFont

    monkeypatch.setattr(settings, "OCR_CROP_BORDER_PIXELS", 32)
    monkeypatch.setattr(settings, "OCR_REGION_PADDING_PIXELS", 8)
    font_path = next(iter(Path("/usr/share/fonts").rglob("DejaVuSerif.ttf")), None)
    if font_path is None:
        pytest.skip("no font to draw the page with")
    page = Image.new("RGB", (1240, 400), "white")
    ImageDraw.Draw(page).text(
        (100, 100),
        "Où sont passés les élèves ? À l'école, évidemment.",
        font=ImageFont.truetype(str(font_path), 34),
        fill="black",
    )
    region = Region(
        type=RegionType.TEXT, score=0.9, reading_order=0, box=Box(x_min=0.05, y_min=0.15, x_max=0.95, y_max=0.45)
    )
    text = TextReader().read(np.asarray(page)[:, :, ::-1].copy(), [region], "doc", 1)
    joined = " ".join(line.text for line in text.regions[0].lines)
    assert "Où sont passés les élèves" in joined and "À l'école" in joined
