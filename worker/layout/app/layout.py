"""PP-DocLayoutV3 (the official ONNX export, run by ONNX Runtime through PaddleOCR's own pre and post processing):
the regions of a page, typed, in reading order."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings
from app.contracts import Box, PageLayout, Region, RegionType

MODEL_VERSION = "PP-DocLayoutV3_onnx"

# The 25 labels of the model (its inference.yml) to what becomes of a region. A label of a newer model that is
# not here is OTHER: kept, typed, and decided on by the assembler - never silently taken for text.
LABEL_TO_TYPE: dict[str, RegionType] = {
    "abstract": RegionType.TEXT,
    "algorithm": RegionType.TEXT,
    "aside_text": RegionType.TEXT,
    "chart": RegionType.IMAGE,
    "content": RegionType.TEXT,
    "display_formula": RegionType.FORMULA,
    "doc_title": RegionType.TITLE,
    "figure_title": RegionType.CAPTION,
    "footer": RegionType.FOOTER,
    "footer_image": RegionType.FOOTER,
    "footnote": RegionType.TEXT,
    # The number beside a formula, and a formula inside a line: the text around them is read as a whole.
    "formula_number": RegionType.OTHER,
    "header": RegionType.HEADER,
    "header_image": RegionType.HEADER,
    "image": RegionType.IMAGE,
    "inline_formula": RegionType.OTHER,
    "number": RegionType.PAGE_NUMBER,
    "paragraph_title": RegionType.TITLE,
    "reference": RegionType.TEXT,
    "reference_content": RegionType.TEXT,
    "seal": RegionType.STAMP,
    "table": RegionType.TABLE,
    "text": RegionType.TEXT,
    "vertical_text": RegionType.TEXT,
    "vision_footnote": RegionType.TEXT,
}


def region_type(label: str) -> RegionType:
    return LABEL_TO_TYPE.get(label, RegionType.OTHER)


# The title of the document, and a section's: the markdown of the page needs to tell them apart.
TITLE_LEVELS: dict[str, int] = {"doc_title": 1, "paragraph_title": 2}


def _make_model() -> Any:
    """The model, loaded from the image's own folder - an offline load: PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK is
    set by the Dockerfile so that PaddleOCR does not even look for a hoster."""
    from paddleocr import LayoutDetection

    model_dir = Path(settings.MODELS_DIR) / settings.LAYOUT_MODEL_NAME
    if not (model_dir / "inference.onnx").is_file():
        raise FileNotFoundError(f"no layout model in {model_dir}")
    engine_config: dict[str, Any] = {"providers": ["CPUExecutionProvider"]}
    if settings.ONNX_INTRA_OP_THREADS > 0:
        engine_config["intra_op_num_threads"] = settings.ONNX_INTRA_OP_THREADS
    return LayoutDetection(
        model_name="PP-DocLayoutV3",
        model_dir=str(model_dir),
        engine="onnxruntime",
        engine_config=engine_config,
        # The lowest score any region is kept from: the finer filter, by type, is build_regions'.
        threshold=min(settings.OCR_REGION_MIN_SCORE, settings.LAYOUT_TABLE_MIN_SCORE),
    )


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """The part of the smaller box that the other covers."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / smaller if smaller > 0 else 0.0


class LayoutDetector:
    """Loads the model on first use, once per process - in the Celery child, not before the fork - and finds the
    regions of a page. `model_factory` is how a test puts a fake in its place."""

    def __init__(self, model_factory: Callable[[], Any] = _make_model) -> None:
        self._model_factory = model_factory
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = self._model_factory()
            return self._model

    def detect(self, image: Any, document_id: str, page_number: int) -> PageLayout:
        """`image`: the page as a BGR array (height, width, 3), as OpenCV holds it."""
        height, width = image.shape[:2]
        found = self._get_model().predict(image, batch_size=1)
        boxes = found[0]["boxes"] if found else []
        return PageLayout(
            document_id=document_id,
            page_number=page_number,
            width_px=width,
            height_px=height,
            regions=build_regions(boxes, width, height),
            model_version=MODEL_VERSION,
        )


def build_regions(boxes: list[dict], width: int, height: int) -> list[Region]:
    """What the model found, as the regions of the contract: the noise and the doubles dropped, the count capped,
    the boxes between 0 and 1, the reading order renumbered from 0 in the order the model gave."""
    kept: list[dict] = []
    for item in boxes:
        x_min, y_min, x_max, y_max = (float(v) for v in item["coordinate"])
        x_min, x_max = max(x_min, 0.0), min(x_max, float(width))
        y_min, y_max = max(y_min, 0.0), min(y_max, float(height))
        if min(x_max - x_min, y_max - y_min) < settings.OCR_REGION_MIN_PIXELS:
            continue
        is_table = region_type(item["label"]) is RegionType.TABLE
        if float(item["score"]) < (settings.LAYOUT_TABLE_MIN_SCORE if is_table else settings.OCR_REGION_MIN_SCORE):
            continue
        kept.append({**item, "_box": (x_min, y_min, x_max, y_max)})

    # The best score first: of two regions that are one, it is the one that stays; and a cap drops the worst.
    by_score = sorted(kept, key=lambda item: -float(item["score"]))
    unique: list[dict] = []
    for item in by_score:
        if any(_overlap(item["_box"], other["_box"]) >= settings.LAYOUT_DUPLICATE_OVERLAP for other in unique):
            continue
        unique.append(item)
    unique = unique[: settings.OCR_MAX_REGIONS_PER_PAGE]

    unique.sort(key=lambda item: item.get("order") if item.get("order") is not None else 10**9)
    regions = []
    for reading_order, item in enumerate(unique):
        x_min, y_min, x_max, y_max = item["_box"]
        polygon = item.get("polygon_points")
        regions.append(
            Region(
                type=region_type(item["label"]),
                score=min(max(float(item["score"]), 0.0), 1.0),
                reading_order=reading_order,
                box=Box(x_min=x_min / width, y_min=y_min / height, x_max=x_max / width, y_max=y_max / height),
                polygon=_polygon(polygon, width, height) if polygon is not None and len(polygon) >= 3 else None,
                title_level=TITLE_LEVELS.get(item["label"]),
            )
        )
    return regions


def _polygon(points: Any, width: int, height: int) -> list[tuple[float, float]]:
    return [(min(max(float(x) / width, 0.0), 1.0), min(max(float(y) / height, 0.0), 1.0)) for x, y in points]


detector = LayoutDetector()
