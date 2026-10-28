"""SLANet_plus and PP-OCRv5 mobile (the official ONNX exports, run by ONNX Runtime through PaddleOCR's own pre and
post processing): the tables of a page - their structure, and the text of each cell.

A table is read from its own crop of the page. SLANet_plus gives its structure as HTML tokens (`<tr>`,
`<td rowspan=..>`) and a box for every cell, in the order of the `<td>`; the OCR reads the lines of text in the crop;
each line is then given to the cell it lies in. A line that covers several cells - the detector joined what the
columns' spacing left close - is cut at the cells, with the pieces of characters the recognizer saw.

What it does not say is how sure it is: the structure's own score is 1.00 on a borderless table it got wrong. So the
score of a table is the structure's, held down by what does not add up - lines of text that lie in no cell, a row
with nothing in it - and the caller decides what a doubtful table is worth."""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.contracts import Box, PageTables, Region, RegionType, TableCell, TableStructure

MODEL_VERSION = "SLANet_plus_onnx+PP-OCRv5_mobile"

Rect = tuple[float, float, float, float]

# A line belongs to a cell when this part of the line lies in it.
_BELONGS = 0.3
# A cell that is a number, an amount, a date: how a header is told from the data under it.
_NUMBERISH = re.compile(r"^[\s\-+–−(]*[\d][\d\s.,:/%€$£)]*\s*[%€$£a-zA-Z]{0,3}$")


@dataclass(frozen=True)
class CellSpec:
    row: int
    col: int
    row_span: int
    col_span: int


class _StructureParser(HTMLParser):
    """The cells of SLANet's HTML, with the row and column each takes - a cell under a `rowspan` pushes the next one
    of its row aside."""

    def __init__(self) -> None:
        super().__init__()
        self.row = -1
        self.cells: list[CellSpec] = []
        self._taken: set[tuple[int, int]] = set()
        self._col = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row += 1
            self._col = 0
        elif tag in ("td", "th"):
            if self.row < 0:  # a cell before any row: the model's output is not a table
                self.row = 0
            options = dict(attrs)
            row_span = _positive(options.get("rowspan"))
            col_span = _positive(options.get("colspan"))
            while (self.row, self._col) in self._taken:
                self._col += 1
            self.cells.append(CellSpec(self.row, self._col, row_span, col_span))
            for r in range(self.row, self.row + row_span):
                for c in range(self._col, self._col + col_span):
                    self._taken.add((r, c))
            self._col += col_span


def _positive(value: str | None) -> int:
    try:
        return max(int(value or 1), 1)
    except ValueError:
        return 1


def parse_structure(tokens: list[str]) -> tuple[int, int, list[CellSpec]]:
    """The size of the table, and its cells in the order of the model's boxes, from SLANet's HTML tokens. A cell that
    spans past the last row or column is cut to the table."""
    parser = _StructureParser()
    parser.feed("".join(tokens))
    if not parser.cells:
        raise ValueError("the model found no cell in the table")
    n_rows = max(cell.row + cell.row_span for cell in parser.cells)
    n_cols = max(cell.col + cell.col_span for cell in parser.cells)
    # `rowspan` past the rows that are really there (the model lets it run on).
    n_rows = min(n_rows, parser.row + 1)
    cells = [
        CellSpec(c.row, c.col, min(c.row_span, n_rows - c.row), min(c.col_span, n_cols - c.col))
        for c in parser.cells
        if c.row < n_rows
    ]
    return n_rows, n_cols, cells


def cell_rect(box: Any) -> Rect:
    """A cell's rectangle from the model's box: four corners (eight numbers) or two (four)."""
    values = [float(v) for v in np.asarray(box).ravel()]
    xs, ys = values[0::2], values[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _area(rect: Rect) -> float:
    return max(rect[2] - rect[0], 0.0) * max(rect[3] - rect[1], 0.0)


def _overlap(a: Rect, b: Rect) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


@dataclass
class Line:
    """A line of text read in the crop: its box, and the pieces of characters the recognizer saw - to cut it at the
    cells when it runs over several."""

    text: str
    score: float
    rect: Rect
    pieces: list[tuple[str, Rect]]


def lines_of(result: dict) -> list[Line]:
    texts, scores, boxes = result.get("rec_texts") or [], result.get("rec_scores") or [], result.get("rec_boxes")
    all_pieces, all_regions = result.get("text_word") or [], result.get("text_word_region") or []
    lines = []
    for index, text in enumerate(texts):
        if not text.strip():
            continue
        rect = tuple(float(v) for v in boxes[index])
        pieces: list[tuple[str, Rect]] = []
        if index < len(all_pieces) and index < len(all_regions) and "".join(all_pieces[index]) == text:
            pieces = [(p, cell_rect(r)) for p, r in zip(all_pieces[index], all_regions[index], strict=True)]
        lines.append(Line(text=text, score=float(scores[index]), rect=rect, pieces=pieces))  # type: ignore[arg-type]
    return lines


def assign_lines(rects: list[Rect], lines: list[Line]) -> tuple[list[list[tuple[float, float, str]]], int]:
    """The text each cell holds, as (top, left, text) in the order they were found - and how many lines lie in no cell.

    A line goes to the cell that holds the most of it; one that lies across several is cut at the cells, with its
    pieces, when it has them (otherwise it goes to the cell that holds the most of it, whole)."""
    held: list[list[tuple[float, float, str]]] = [[] for _ in rects]
    outside = 0
    for line in lines:
        area = _area(line.rect) or 1.0
        inside = [(_overlap(line.rect, rect) / area, index) for index, rect in enumerate(rects)]
        belongs = [index for share, index in inside if share >= _BELONGS]
        if not belongs:
            # Not even a third of it in any cell: the nearest, if the line's centre is in one.
            centre = ((line.rect[0] + line.rect[2]) / 2, (line.rect[1] + line.rect[3]) / 2)
            at = [i for i, r in enumerate(rects) if r[0] <= centre[0] <= r[2] and r[1] <= centre[1] <= r[3]]
            if at:
                belongs = at[:1]
            else:
                outside += 1
                continue
        if len(belongs) > 1 and line.pieces:
            per_cell: dict[int, list[str]] = {}
            for piece, rect in line.pieces:
                centre_x, centre_y = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
                target = next(
                    (
                        i
                        for i in belongs
                        if rects[i][0] <= centre_x <= rects[i][2] and rects[i][1] <= centre_y <= rects[i][3]
                    ),
                    None,
                )
                if target is None:
                    target = max(belongs, key=lambda i: _overlap(rect, rects[i]))
                per_cell.setdefault(target, []).append(piece)
            for target, pieces in per_cell.items():
                text = "".join(pieces).strip()
                if text:
                    held[target].append((line.rect[1], line.rect[0], text))
            continue
        target = max(belongs, key=lambda i: _overlap(line.rect, rects[i]))
        held[target].append((line.rect[1], line.rect[0], line.text.strip()))
    return held, outside


def cell_text(held: list[tuple[float, float, str]]) -> str:
    """What a cell holds, top to bottom then left to right, on one line."""
    return " ".join(text for _, _, text in sorted(held, key=lambda item: (round(item[0] / 8), item[1])))


def looks_like_header(first_row: list[str], has_more_rows: bool) -> bool:
    """Whether a table's first row is its header: there is something under it, each of its cells says something, and
    most of them are words rather than the numbers the rows under a header carry."""
    if not has_more_rows or not first_row or any(not text.strip() for text in first_row):
        return False
    numbers = sum(1 for text in first_row if _NUMBERISH.match(text.strip()))
    return numbers * 2 < len(first_row)


def table_score(structure_score: float, lines: int, outside: int, empty_rows: int, empty_spans: int = 0) -> float:
    """How far to trust the table: the structure's own score, held down by the lines of text that lie in no cell, by a
    row with nothing in it, and by a merged cell with nothing in it - what a structure the model made up looks like (a
    borderless table it read as having a header spread over two rows scored 0.98 on its own)."""
    coverage = (lines - outside) / lines if lines else 0.0
    score = min(structure_score, coverage)
    if empty_rows or empty_spans:
        score *= 0.5
    return round(max(min(score, 1.0), 0.0), 3)


def build_table(
    region: Region,
    structure: dict,
    lines: list[Line],
    offset: tuple[int, int],
    page_size: tuple[int, int],
) -> TableStructure:
    """The table of a region from SLANet's answer and the lines read in its crop. `offset`: where the crop's top left
    corner is on the page, in pixels; `page_size`: the page's width and height."""
    n_rows, n_cols, specs = parse_structure(list(structure["structure"]))
    boxes = list(structure["bbox"])
    if len(boxes) != len(specs):
        # The boxes are the cells, in order: with one too many or too few, no text can be given to its cell.
        raise ValueError(f"the model found {len(specs)} cells and {len(boxes)} boxes")
    if len(specs) > settings.TABLE_MAX_CELLS:
        raise ValueError(f"a table of {len(specs)} cells is not read")
    rects = [cell_rect(box) for box in boxes]
    held, outside = assign_lines(rects, lines)
    texts = [cell_text(h) for h in held]

    width, height = page_size
    ox, oy = offset

    def normalized(rect: Rect) -> Box:
        return Box(
            x_min=min(max((rect[0] + ox) / width, 0.0), 1.0),
            y_min=min(max((rect[1] + oy) / height, 0.0), 1.0),
            x_max=min(max((rect[2] + ox) / width, 0.0), 1.0),
            y_max=min(max((rect[3] + oy) / height, 0.0), 1.0),
        )

    cells = [
        TableCell(
            row=spec.row, col=spec.col, row_span=spec.row_span, col_span=spec.col_span, text=text, box=normalized(rect)
        )
        for spec, text, rect in zip(specs, texts, rects, strict=True)
    ]
    first_row = [cell.text for cell in cells if cell.row == 0]
    rows_with_text = {cell.row + k for cell in cells if cell.text.strip() for k in range(cell.row_span)}
    empty_rows = n_rows - len(rows_with_text & set(range(n_rows)))
    empty_spans = sum(1 for cell in cells if not cell.text.strip() and (cell.row_span > 1 or cell.col_span > 1))
    return TableStructure(
        region_order=region.reading_order,
        n_rows=n_rows,
        n_cols=n_cols,
        cells=cells,
        has_header=looks_like_header(first_row, n_rows > 1),
        score=table_score(float(structure.get("structure_score") or 0.0), len(lines), outside, empty_rows, empty_spans),
    )


def _engine_config() -> dict[str, Any]:
    config: dict[str, Any] = {"providers": ["CPUExecutionProvider"]}
    if settings.ONNX_INTRA_OP_THREADS > 0:
        config["intra_op_num_threads"] = settings.ONNX_INTRA_OP_THREADS
    return config


def _model_dir(name: str) -> Path:
    folder = Path(settings.MODELS_DIR) / name
    if not (folder / "inference.onnx").is_file():
        raise FileNotFoundError(f"no table model in {folder}")
    return folder


def _make_structure() -> Any:
    """SLANet_plus, loaded from the image's own folder - an offline load (PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK is set
    by the Dockerfile, so that PaddleOCR does not even look for a hoster)."""
    from paddleocr import TableStructureRecognition

    return TableStructureRecognition(
        model_name="SLANet_plus",
        model_dir=str(_model_dir(settings.TABLE_MODEL_NAME)),
        engine="onnxruntime",
        engine_config=_engine_config(),
    )


def _make_ocr() -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir=str(_model_dir(settings.OCR_DET_MODEL_NAME)),
        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
        text_recognition_model_dir=str(_model_dir(settings.OCR_REC_MODEL_NAME)),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        engine="onnxruntime",
        engine_config=_engine_config(),
    )


def crop_table(image: np.ndarray, region: Region, margin: int) -> tuple[np.ndarray, tuple[int, int]]:
    """The region's crop of the page, with a margin cut at the page's edge, and where its top left corner is."""
    height, width = image.shape[:2]
    x0 = max(round(region.box.x_min * width) - margin, 0)
    y0 = max(round(region.box.y_min * height) - margin, 0)
    x1 = min(round(region.box.x_max * width) + margin, width)
    y1 = min(round(region.box.y_max * height) + margin, height)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the table's region is empty")
    return image[y0:y1, x0:x1].copy(), (x0, y0)


class TableReader:
    """Loads the models on first use, once per process - in the Celery child, not before the fork - and reads the tables
    of a page. The factories are how a test puts fakes in their place."""

    def __init__(
        self,
        structure_factory: Callable[[], Any] = _make_structure,
        ocr_factory: Callable[[], Any] = _make_ocr,
    ) -> None:
        self._structure_factory, self._ocr_factory = structure_factory, ocr_factory
        self._structure: Any = None
        self._ocr: Any = None
        self._lock = threading.Lock()

    def _models(self) -> tuple[Any, Any]:
        with self._lock:
            if self._structure is None:
                self._structure = self._structure_factory()
            if self._ocr is None:
                self._ocr = self._ocr_factory()
            return self._structure, self._ocr

    def read(self, image: np.ndarray, regions: list[Region], document_id: str, page_number: int) -> PageTables:
        """`image`: the page as a BGR array (height, width, 3). Only the table regions are read, in reading order."""
        height, width = image.shape[:2]
        structure_model, ocr = self._models()
        tables = []
        for region in [r for r in regions if r.type is RegionType.TABLE][: settings.TABLE_MAX_PER_PAGE]:
            crop, offset = crop_table(image, region, settings.TABLE_CROP_MARGIN_PIXELS)
            found = structure_model.predict(crop)
            if not found:
                raise ValueError(f"the model read nothing in the table of region {region.reading_order}")
            lines = lines_of(ocr.predict(crop, return_word_box=True)[0])
            tables.append(build_table(region, found[0], lines, offset, (width, height)))
        return PageTables(document_id=document_id, page_number=page_number, tables=tables, model_version=MODEL_VERSION)


reader = TableReader()
