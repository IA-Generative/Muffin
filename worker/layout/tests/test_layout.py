"""The layout pod: what becomes of the model's boxes (app/layout.py) and the task around it (app/tasks.py)."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app import layout as layout_module
from app.config import settings
from app.contracts import PageLayout, RegionType
from app.layout import LABEL_TO_TYPE, LayoutDetector, build_regions, region_type

WIDTH, HEIGHT = 1000, 2000

# The labels of the model, as its inference.yml lists them.
MODEL_LABELS = [
    "abstract", "algorithm", "aside_text", "chart", "content", "display_formula", "doc_title", "figure_title",
    "footer", "footer_image", "footnote", "formula_number", "header", "header_image", "image", "inline_formula",
    "number", "paragraph_title", "reference", "reference_content", "seal", "table", "text", "vertical_text",
    "vision_footnote",
]  # fmt: skip


def _box(label="text", score=0.9, coordinate=(100, 200, 500, 400), order=1, polygon=True) -> dict:
    x0, y0, x1, y1 = coordinate
    return {
        "cls_id": 0,
        "label": label,
        "score": score,
        "coordinate": [x0, y0, x1, y1],
        "order": order,
        "polygon_points": np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32) if polygon else None,
    }


def test_every_label_of_the_model_has_a_type():
    assert set(MODEL_LABELS) == set(LABEL_TO_TYPE)


def test_a_label_the_model_did_not_have_is_other_not_text():
    assert region_type("handwriting") is RegionType.OTHER


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("text", RegionType.TEXT),
        ("doc_title", RegionType.TITLE),
        ("paragraph_title", RegionType.TITLE),
        ("figure_title", RegionType.CAPTION),
        ("table", RegionType.TABLE),
        ("image", RegionType.IMAGE),
        ("chart", RegionType.IMAGE),
        ("display_formula", RegionType.FORMULA),
        ("seal", RegionType.STAMP),
        ("header", RegionType.HEADER),
        ("header_image", RegionType.HEADER),
        ("footer", RegionType.FOOTER),
        ("footer_image", RegionType.FOOTER),
        ("number", RegionType.PAGE_NUMBER),
    ],
)
def test_the_labels_become_the_types_of_the_contract(label, expected):
    assert region_type(label) is expected


def test_the_boxes_become_regions_between_0_and_1():
    [region] = build_regions([_box(coordinate=(100, 200, 500, 400))], WIDTH, HEIGHT)
    assert (region.box.x_min, region.box.y_min, region.box.x_max, region.box.y_max) == (0.1, 0.1, 0.5, 0.2)
    assert region.type is RegionType.TEXT
    assert region.polygon is not None and len(region.polygon) == 4
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in region.polygon)


def test_a_title_says_its_level_and_nothing_else_does():
    regions = build_regions(
        [
            _box("doc_title", coordinate=(100, 100, 500, 200), order=1),
            _box("paragraph_title", coordinate=(100, 300, 500, 400), order=2),
            _box("text", coordinate=(100, 500, 500, 600), order=3),
        ],
        WIDTH,
        HEIGHT,
    )
    assert [region.title_level for region in regions] == [1, 2, None]


def test_a_box_past_the_page_is_cut_to_it():
    [region] = build_regions([_box(coordinate=(-30, 1900, 1100, 2100))], WIDTH, HEIGHT)
    assert (region.box.x_min, region.box.x_max, region.box.y_max) == (0.0, 1.0, 1.0)


def test_the_regions_come_in_the_models_reading_order_renumbered_from_0():
    boxes = [
        _box("text", coordinate=(100, 900, 500, 1000), order=3),
        _box("doc_title", coordinate=(100, 100, 500, 200), order=1),
        _box("text", coordinate=(100, 400, 500, 500), order=2),
    ]
    regions = build_regions(boxes, WIDTH, HEIGHT)
    assert [region.reading_order for region in regions] == [0, 1, 2]
    assert [region.type for region in regions] == [RegionType.TITLE, RegionType.TEXT, RegionType.TEXT]
    assert [round(region.box.y_min, 2) for region in regions] == [0.05, 0.2, 0.45]


def test_a_region_without_order_goes_last():
    regions = build_regions(
        [_box(coordinate=(100, 100, 500, 200), order=None), _box(coordinate=(100, 400, 500, 500), order=2)],
        WIDTH,
        HEIGHT,
    )
    assert [round(region.box.y_min, 2) for region in regions] == [0.2, 0.05]


def test_a_low_score_is_noise():
    assert build_regions([_box(score=settings.OCR_REGION_MIN_SCORE - 0.01)], WIDTH, HEIGHT) == []


def test_a_table_is_kept_from_a_lower_score():
    score = (settings.LAYOUT_TABLE_MIN_SCORE + settings.OCR_REGION_MIN_SCORE) / 2
    assert [r.type for r in build_regions([_box("table", score=score)], WIDTH, HEIGHT)] == [RegionType.TABLE]
    assert build_regions([_box("image", score=score)], WIDTH, HEIGHT) == []
    assert build_regions([_box("table", score=settings.LAYOUT_TABLE_MIN_SCORE - 0.01)], WIDTH, HEIGHT) == []


def test_a_speck_is_dropped():
    tiny = settings.OCR_REGION_MIN_PIXELS - 1
    assert build_regions([_box(coordinate=(100, 100, 100 + tiny, 400))], WIDTH, HEIGHT) == []
    assert build_regions([_box(coordinate=(100, 100, 500, 100 + tiny))], WIDTH, HEIGHT) == []


def test_two_boxes_that_are_one_region_keep_the_better_score():
    twice = [
        _box("text", score=0.7, coordinate=(100, 200, 500, 400), order=1),
        _box("text", score=0.9, coordinate=(102, 202, 498, 398), order=2),
    ]
    [region] = build_regions(twice, WIDTH, HEIGHT)
    assert region.score == 0.9


def test_a_box_that_only_touches_another_stays():
    side_by_side = [_box(coordinate=(100, 200, 500, 400), order=1), _box(coordinate=(500, 200, 900, 400), order=2)]
    assert len(build_regions(side_by_side, WIDTH, HEIGHT)) == 2


def test_the_count_is_capped_and_the_lowest_scores_go(monkeypatch):
    monkeypatch.setattr(settings, "OCR_MAX_REGIONS_PER_PAGE", 2)
    boxes = [
        _box(score=0.6, coordinate=(100, 100, 500, 200), order=1),
        _box(score=0.95, coordinate=(100, 300, 500, 400), order=2),
        _box(score=0.8, coordinate=(100, 500, 500, 600), order=3),
    ]
    regions = build_regions(boxes, WIDTH, HEIGHT)
    assert [region.score for region in regions] == [0.95, 0.8]
    assert [region.reading_order for region in regions] == [0, 1]


def test_a_box_without_polygon_has_none():
    [region] = build_regions([_box(polygon=False)], WIDTH, HEIGHT)
    assert region.polygon is None


def test_no_box_is_no_region():
    assert build_regions([], WIDTH, HEIGHT) == []


class FakeModel:
    def __init__(self, boxes):
        self.boxes = boxes
        self.calls = 0

    def predict(self, image, batch_size=1):
        self.calls += 1
        return [{"boxes": self.boxes}]


def test_the_detector_gives_a_page_layout_of_the_contract():
    detector = LayoutDetector(lambda: FakeModel([_box("doc_title", coordinate=(100, 100, 500, 200))]))
    layout = detector.detect(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "doc-1", 4)
    assert isinstance(layout, PageLayout)
    assert (layout.document_id, layout.page_number, layout.width_px, layout.height_px) == ("doc-1", 4, WIDTH, HEIGHT)
    assert [region.type for region in layout.regions] == [RegionType.TITLE]
    assert layout.model_version == layout_module.MODEL_VERSION
    assert PageLayout.model_validate_json(layout.model_dump_json()) == layout


def test_a_page_without_region_is_a_valid_empty_layout():
    detector = LayoutDetector(lambda: FakeModel([]))
    assert detector.detect(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "doc-1", 1).regions == []


def test_the_model_is_loaded_once_for_many_pages():
    loads = []

    def factory():
        loads.append(1)
        return FakeModel([])

    detector = LayoutDetector(factory)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    for page in (1, 2, 3):
        detector.detect(image, "doc", page)
    assert len(loads) == 1


def test_the_model_is_not_loaded_before_it_is_needed():
    loads = []
    LayoutDetector(lambda: loads.append(1))
    assert loads == []


def test_a_missing_model_fails_with_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODELS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="no layout model"):
        layout_module._make_model()


def _png(width=120, height=80) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_task_reads_the_page_from_storage_and_gives_the_layout_in_json(monkeypatch):
    from app import tasks

    asked = []
    seen = {}

    class Storage:
        def get_object(self, key):
            asked.append(key)
            return _png(120, 80)

    class Detector:
        def detect(self, image, document_id, page_number):
            seen["shape"] = image.shape
            seen["first_pixel_bgr"] = image[0, 0].tolist()
            return PageLayout(
                document_id=document_id, page_number=page_number, width_px=120, height_px=80, model_version="fake"
            )

    monkeypatch.setattr(tasks, "storage", Storage())
    monkeypatch.setattr(tasks, "detector", Detector())
    result = tasks.layout_page("doc-1", 2, "ocr-pages/doc-1/page-2.png")
    assert asked == ["ocr-pages/doc-1/page-2.png"]
    # The model gets a BGR array, as OpenCV holds a page: the image's (10, 20, 30) RGB is (30, 20, 10) here.
    assert seen == {"shape": (80, 120, 3), "first_pixel_bgr": [30, 20, 10]}
    assert PageLayout.model_validate(result).page_number == 2
    assert result["regions"] == []


def test_the_task_is_on_the_layout_queue_under_the_name_the_extraction_worker_sends_to():
    from app.celery_app import celery_app

    assert "app.tasks.layout_page" in celery_app.tasks
    assert celery_app.conf.task_default_queue == settings.LAYOUT_QUEUE_NAME == "document_layout"
    [queue] = celery_app.conf.task_queues
    assert queue.exchange.name == queue.routing_key == queue.name == settings.LAYOUT_QUEUE_NAME


# --- the real model: skipped where it is not (the image of the pod has it; so does a machine that ran PaddleOCR) ---

_REAL_MODEL = Path(os.environ.get("MODELS_DIR", settings.MODELS_DIR)) / settings.LAYOUT_MODEL_NAME / "inference.onnx"


@pytest.mark.slow
@pytest.mark.skipif(not _REAL_MODEL.is_file(), reason=f"no model at {_REAL_MODEL}")
def test_the_real_model_finds_a_title_a_paragraph_and_an_image_on_a_drawn_page():
    from PIL import ImageDraw

    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    draw.text((120, 100), "Rapport annuel d'activite", fill="black")
    for row in range(8):
        draw.text(
            (120, 300 + row * 40), "Le service a traite de nombreux dossiers au cours de l'exercice.", fill="black"
        )
    for x in range(120, 520):
        for y in range(900, 1250):
            page.putpixel((x, y), (60 + x % 90, 90 + y % 100, 140))
    detector = LayoutDetector()
    layout = detector.detect(np.asarray(page)[:, :, ::-1].copy(), "doc", 1)
    types = {region.type for region in layout.regions}
    assert RegionType.IMAGE in types
    assert layout.regions == sorted(layout.regions, key=lambda region: region.reading_order)
