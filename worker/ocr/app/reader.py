"""PP-OCRv5 mobile (the official ONNX exports, run by ONNX Runtime through PaddleOCR's own pre and post processing):
the lines and words of the text regions of a page.

A region is read from its own crop of the page, so what the layout found around it is not read with it: every region
that is not text - a table, an image, a formula, a logo, a running header - is painted white in the crop first."""

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.contracts import Box, OcrLine, OcrWord, PageText, Region, RegionText, RegionType

MODEL_VERSION = "PP-OCRv5_mobile_det+latin_PP-OCRv5_mobile_rec"

# Painted white in a crop before it is read. Not OTHER: a formula inside a line is an OTHER region that lies
# inside the text region, and erasing it would cut the sentence.
_MASKED_TYPES = frozenset(
    {
        RegionType.TABLE,
        RegionType.IMAGE,
        RegionType.FORMULA,
        RegionType.LOGO,
        RegionType.STAMP,
        RegionType.HEADER,
        RegionType.FOOTER,
        RegionType.PAGE_NUMBER,
    }
)


def _make_model() -> Any:
    """The two models, loaded from the image's own folder - an offline load: PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK
    is set by the Dockerfile so that PaddleOCR does not even look for a hoster."""
    from paddleocr import PaddleOCR

    root = Path(settings.MODELS_DIR)
    det_dir, rec_dir = root / settings.OCR_DET_MODEL_NAME, root / settings.OCR_REC_MODEL_NAME
    for folder in (det_dir, rec_dir):
        if not (folder / "inference.onnx").is_file():
            raise FileNotFoundError(f"no OCR model in {folder}")
    engine_config: dict[str, Any] = {"providers": ["CPUExecutionProvider"]}
    if settings.ONNX_INTRA_OP_THREADS > 0:
        engine_config["intra_op_num_threads"] = settings.ONNX_INTRA_OP_THREADS
    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir=str(det_dir),
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=str(rec_dir),
        # The layout already gave the page's regions: a crop is read as it is.
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        engine="onnxruntime",
        engine_config=engine_config,
    )


def _pixels(box: Box, width: int, height: int) -> tuple[int, int, int, int]:
    return round(box.x_min * width), round(box.y_min * height), round(box.x_max * width), round(box.y_max * height)


def crop_region(image: np.ndarray, region: Region, others: list[Region]) -> tuple[np.ndarray, int, int]:
    """The region's crop (a copy), padded, with the masked regions that fall in it painted white and a white border
    around it; and where the top left corner of the crop is on the page - negative, the border being outside it."""
    height, width = image.shape[:2]
    pad = settings.OCR_REGION_PADDING_PIXELS
    x0, y0, x1, y1 = _pixels(region.box, width, height)
    x0, y0, x1, y1 = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, width), min(y1 + pad, height)
    crop = image[y0:y1, x0:x1].copy()
    for other in others:
        if other.type not in _MASKED_TYPES:
            continue
        ox0, oy0, ox1, oy1 = _pixels(other.box, width, height)
        ox0, oy0, ox1, oy1 = max(ox0, x0) - x0, max(oy0, y0) - y0, min(ox1, x1) - x0, min(oy1, y1) - y0
        if ox0 < ox1 and oy0 < oy1:
            crop[oy0:oy1, ox0:ox1] = 255
    border = settings.OCR_CROP_BORDER_PIXELS
    if border > 0:
        crop = np.pad(crop, ((border, border), (border, border), (0, 0)), constant_values=255)
    return crop, x0 - border, y0 - border


def build_words(
    text: str,
    segments: list[str] | None,
    segment_boxes: list[tuple[float, float, float, float]] | None,
    line: tuple[float, float, float, float],
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """The words of a line, each with its box (in the crop's pixels).

    PaddleOCR places the pieces its recognizer saw - a run of letters, an apostrophe, an accented letter with the
    space after it - not words. So the line is cut at its blanks, and the box of a word is the union of the pieces
    that cover its characters. A line whose pieces do not add up to its text is cut in proportion to the characters
    instead."""
    words = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not words:
        return []
    if segments and segment_boxes and len(segments) == len(segment_boxes) and "".join(segments) == text:
        spans, start = [], 0
        for segment in segments:
            spans.append((start, start + len(segment)))
            start += len(segment)
        result = []
        for word, begin, end in words:
            covering = [box for (s, e), box in zip(spans, segment_boxes, strict=True) if s < end and e > begin]
            if not covering:
                continue
            result.append(
                (
                    word,
                    (
                        min(box[0] for box in covering),
                        min(box[1] for box in covering),
                        max(box[2] for box in covering),
                        max(box[3] for box in covering),
                    ),
                )
            )
        if len(result) == len(words):
            return result
    x0, y0, x1, y1 = line
    width, total = x1 - x0, max(len(text), 1)
    return [(word, (x0 + width * begin / total, y0, x0 + width * end / total, y1)) for word, begin, end in words]


def _unit(value: float, size: float) -> float:
    return min(max(value / size, 0.0), 1.0)


def _box(pixels: tuple[float, float, float, float], x_offset: int, y_offset: int, width: int, height: int) -> Box:
    x0, y0, x1, y1 = pixels
    return Box(
        x_min=_unit(x0 + x_offset, width),
        y_min=_unit(y0 + y_offset, height),
        x_max=_unit(x1 + x_offset, width),
        y_max=_unit(y1 + y_offset, height),
    )


def _quad_box(quad: Any) -> tuple[float, float, float, float]:
    xs, ys = [float(point[0]) for point in quad], [float(point[1]) for point in quad]
    return min(xs), min(ys), max(xs), max(ys)


def lines_of(result: dict, x_offset: int, y_offset: int, width: int, height: int) -> list[OcrLine]:
    """What PaddleOCR read in one crop, as the contract's lines: boxes in the page's frame, between 0 and 1."""
    texts, scores, boxes = result.get("rec_texts") or [], result.get("rec_scores") or [], result.get("rec_boxes")
    all_segments, all_regions = result.get("text_word") or [], result.get("text_word_region") or []
    lines = []
    for index, text in enumerate(texts):
        score = float(scores[index])
        if not text.strip() or score < settings.OCR_LINE_MIN_SCORE:
            continue
        line_box = tuple(float(v) for v in boxes[index])
        segments = all_segments[index] if index < len(all_segments) else None
        segment_boxes = [_quad_box(quad) for quad in all_regions[index]] if index < len(all_regions) else None
        words = [
            OcrWord(text=word, score=score, box=_box(word_box, x_offset, y_offset, width, height))
            for word, word_box in build_words(text, segments, segment_boxes, line_box)
        ]
        lines.append(
            OcrLine(text=text, score=score, box=_box(line_box, x_offset, y_offset, width, height), words=words)
        )
    return lines


class TextReader:
    """Loads the models on first use, once per process - in the Celery child, not before the fork - and reads the
    text regions of a page. `model_factory` is how a test puts a fake in its place."""

    def __init__(self, model_factory: Callable[[], Any] = _make_model) -> None:
        self._model_factory = model_factory
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = self._model_factory()
            return self._model

    def read(self, image: np.ndarray, regions: list[Region], document_id: str, page_number: int) -> PageText:
        """`image`: the page as a BGR array (height, width, 3), as OpenCV holds it. Only the text regions are read,
        each from its own crop; a region without text has no line."""
        height, width = image.shape[:2]
        model = self._get_model()
        texts = []
        for region in regions:
            if not region.type.is_text:
                continue
            crop, x_offset, y_offset = crop_region(image, region, [other for other in regions if other is not region])
            found = model.predict(crop, return_word_box=True)
            lines = lines_of(found[0], x_offset, y_offset, width, height) if found else []
            texts.append(RegionText(region_order=region.reading_order, lines=lines))
        return PageText(document_id=document_id, page_number=page_number, regions=texts, model_version=MODEL_VERSION)


reader = TextReader()
