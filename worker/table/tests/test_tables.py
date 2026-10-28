"""The table pod: the structure, the text given to its cells, the score (app/tables.py), and the task around them."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app import tables as tables_module
from app.config import settings
from app.contracts import Box, PageTables, Region, RegionType
from app.tables import (
    Line,
    TableReader,
    assign_lines,
    build_table,
    cell_rect,
    cell_text,
    crop_table,
    lines_of,
    looks_like_header,
    parse_structure,
    table_score,
)

# --- the structure ---


def _html(*rows: str) -> list[str]:
    """SLANet's tokens: `<td` and its attributes and `>` are separate tokens."""
    tokens = ["<html>", "<body>", "<table>"]
    for row in rows:
        tokens.append("<tr>")
        for cell in row.split():
            spans = cell.split(":")[1:] if ":" in cell else []
            if spans:
                tokens.append("<td")
                tokens.extend(f' {key}="{value}"' for key, value in (span.split("=") for span in spans))
                tokens.extend([">", "</td>"])
            else:
                tokens.append("<td></td>")
        tokens.append("</tr>")
    return [*tokens, "</table>", "</body>", "</html>"]


def test_a_plain_grid_is_read_row_by_row():
    n_rows, n_cols, cells = parse_structure(_html("a b c", "d e f"))
    assert (n_rows, n_cols, len(cells)) == (2, 3, 6)
    assert [(c.row, c.col) for c in cells] == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]


def test_a_cell_that_spans_columns_takes_their_place():
    n_rows, n_cols, cells = parse_structure(_html("a:colspan=3 b", "c d e f"))
    assert (n_rows, n_cols) == (2, 4)
    assert (cells[0].col, cells[0].col_span, cells[1].col) == (0, 3, 3)


def test_a_cell_that_spans_rows_pushes_the_next_one_of_the_rows_under_it_aside():
    n_rows, n_cols, cells = parse_structure(_html("a:rowspan=2 b", "c"))
    assert (n_rows, n_cols) == (2, 2)
    by_place = {(c.row, c.col): c for c in cells}
    # The second row's only cell is at column 1: column 0 is taken by the cell above.
    assert set(by_place) == {(0, 0), (0, 1), (1, 1)}
    assert by_place[(0, 0)].row_span == 2


def test_a_row_with_more_cells_than_the_rows_above_widens_the_table():
    n_rows, n_cols, cells = parse_structure(_html("a:rowspan=2 b", "c d"))
    assert (n_rows, n_cols) == (2, 3)
    assert {(c.row, c.col) for c in cells} == {(0, 0), (0, 1), (1, 1), (1, 2)}


def test_a_span_past_the_table_is_cut_to_it():
    n_rows, n_cols, cells = parse_structure(_html("a:rowspan=5 b"))
    assert (n_rows, cells[0].row_span) == (1, 1)


def test_a_structure_without_a_cell_is_not_a_table():
    with pytest.raises(ValueError, match="no cell"):
        parse_structure(["<html>", "<body>", "<table>", "</table>", "</body>", "</html>"])


def test_the_attributes_of_a_span_are_tolerated_when_they_are_not_numbers():
    _, _, cells = parse_structure(["<td", ' colspan="x"', ">", "</td>"])
    assert cells[0].col_span == 1


def test_a_cell_rectangle_comes_from_four_corners_or_two():
    assert cell_rect([5, 32, 373, 33, 364, 161, 4, 159]) == (4, 32, 373, 161)
    assert cell_rect([10, 20, 30, 40]) == (10, 20, 30, 40)


# --- the text given to the cells ---


def _line(text, x0, y0, x1, y1, pieces=None) -> Line:
    return Line(text=text, score=0.95, rect=(x0, y0, x1, y1), pieces=pieces or [])


RECTS = [(0, 0, 100, 50), (100, 0, 200, 50), (0, 50, 100, 100), (100, 50, 200, 100)]


def test_each_line_goes_to_the_cell_it_lies_in():
    lines = [_line("a", 10, 10, 60, 40), _line("b", 110, 10, 160, 40), _line("c", 10, 60, 60, 90)]
    held, outside = assign_lines(RECTS, lines)
    assert [cell_text(h) for h in held] == ["a", "b", "c", ""]
    assert outside == 0


def test_a_line_that_runs_over_two_cells_is_cut_at_them_with_its_pieces():
    pieces = [("Bre", (10, 10, 40, 40)), ("tagne ", (40, 10, 90, 40)), ("3 340", (110, 10, 160, 40))]
    held, _ = assign_lines(RECTS, [_line("Bretagne 3 340", 10, 10, 160, 40, pieces)])
    assert [cell_text(h) for h in held[:2]] == ["Bretagne", "3 340"]


def test_a_line_that_runs_over_two_cells_without_pieces_goes_whole_to_the_one_with_most_of_it():
    held, _ = assign_lines(RECTS, [_line("Bretagne 3 340", 10, 10, 160, 40)])
    assert cell_text(held[0]) == "Bretagne 3 340" and cell_text(held[1]) == ""


def test_a_line_in_no_cell_is_counted_and_not_lost_in_one():
    held, outside = assign_lines(RECTS, [_line("far", 400, 400, 450, 430), _line("a", 10, 10, 60, 40)])
    assert outside == 1 and [cell_text(h) for h in held] == ["a", "", "", ""]


def test_a_line_mostly_outside_a_cell_but_centred_in_it_still_goes_there():
    held, outside = assign_lines([(0, 0, 40, 40)], [_line("wide", 18, 10, 190, 30)])
    assert outside == 1  # its centre (104) is not in the cell


def test_the_lines_of_a_cell_are_read_top_to_bottom_then_left_to_right():
    held, _ = assign_lines(
        [(0, 0, 200, 200)],
        [
            _line("troisième", 120, 100, 190, 120),
            _line("première", 10, 10, 90, 30),
            _line("deuxième", 100, 12, 190, 32),
        ],
    )
    assert cell_text(held[0]) == "première deuxième troisième"


def test_the_lines_come_from_what_paddleocr_read_and_the_blank_ones_are_dropped():
    result = {
        "rec_texts": ["Année", "  ", "2024"],
        "rec_scores": [0.99, 0.9, 0.98],
        "rec_boxes": np.array([[0, 0, 50, 20], [0, 30, 50, 50], [60, 0, 110, 20]]),
        "text_word": [["Ann", "ée"], [" "], ["2024"]],
        "text_word_region": [
            [[(0, 0), (30, 0), (30, 20), (0, 20)], [(30, 0), (50, 0), (50, 20), (30, 20)]],
            [],
            [[(60, 0), (110, 0), (110, 20), (60, 20)]],
        ],
    }
    lines = lines_of(result)
    assert [line.text for line in lines] == ["Année", "2024"]
    assert [piece for piece, _ in lines[0].pieces] == ["Ann", "ée"]


def test_pieces_that_do_not_make_the_text_are_not_trusted():
    lines = lines_of(
        {
            "rec_texts": ["Année"],
            "rec_scores": [0.9],
            "rec_boxes": np.array([[0, 0, 50, 20]]),
            "text_word": [["Xx"]],
            "text_word_region": [[[(0, 0), (9, 9)]]],
        }
    )
    assert lines[0].pieces == []


# --- header, score ---


@pytest.mark.parametrize(
    ("row", "more", "expected"),
    [
        (["Année", "Dossiers", "Délai (j)", "Coût (€)"], True, True),
        (["2023", "1 120", "34", "12 450,00"], True, False),
        (["Année", "", "Délai"], True, False),
        (["Année", "Total"], False, False),
        (["Région", "Habitants", "2024"], True, True),
        (["2023", "2024", "Total"], True, False),
        ([], True, False),
    ],
)
def test_a_first_row_is_a_header_when_it_says_something_in_every_cell_and_is_not_numbers(row, more, expected):
    assert looks_like_header(row, more) is expected


def test_the_score_is_the_structures_held_down_by_what_does_not_add_up():
    assert table_score(0.99, lines=10, outside=0, empty_rows=0) == 0.99
    assert table_score(0.99, lines=10, outside=4, empty_rows=0) == 0.6
    assert table_score(1.0, lines=10, outside=0, empty_rows=1) == 0.5
    assert table_score(1.0, lines=10, outside=0, empty_rows=0, empty_spans=1) == 0.5
    assert table_score(1.0, lines=0, outside=0, empty_rows=0) == 0.0


# --- a table ---

PAGE = (1000, 2000)


def _region(order=0, box=(0.1, 0.2, 0.6, 0.3), type_=RegionType.TABLE) -> Region:
    x0, y0, x1, y1 = box
    return Region(type=type_, score=0.9, reading_order=order, box=Box(x_min=x0, y_min=y0, x_max=x1, y_max=y1))


def _structure(rows=2, cols=2, score=0.99, cell=(100, 50)):
    boxes = [[c * cell[0], r * cell[1], (c + 1) * cell[0], (r + 1) * cell[1]] for r in range(rows) for c in range(cols)]
    tokens = _html(*[" ".join("x" for _ in range(cols)) for _ in range(rows)])
    return {"structure": tokens, "bbox": boxes, "structure_score": score}


def _lines_2x2():
    return [
        _line("Année", 10, 10, 90, 40),
        _line("Total", 110, 10, 190, 40),
        _line("2024", 10, 60, 90, 90),
        _line("12", 110, 60, 190, 90),
    ]


def test_a_table_has_its_grid_its_texts_and_boxes_on_the_page():
    table = build_table(_region(3), _structure(), _lines_2x2(), offset=(100, 400), page_size=PAGE)
    assert (table.region_order, table.n_rows, table.n_cols) == (3, 2, 2)
    assert [(c.row, c.col, c.text) for c in table.cells] == [
        (0, 0, "Année"),
        (0, 1, "Total"),
        (1, 0, "2024"),
        (1, 1, "12"),
    ]
    # The crop starts at (100, 400) of a 1000 x 2000 page: its first cell, 100 x 50, is at 0.1,0.2 - 0.2,0.225.
    box = table.cells[0].box
    assert (box.x_min, box.y_min, box.x_max, box.y_max) == (0.1, 0.2, 0.2, 0.225)
    assert table.has_header and table.score == 0.99
    assert PageTables.model_validate(
        {"document_id": "d", "page_number": 1, "tables": [table.model_dump()], "model_version": "m"}
    )


def test_a_table_whose_boxes_are_not_its_cells_is_refused():
    structure = _structure()
    structure["bbox"] = structure["bbox"][:-1]
    with pytest.raises(ValueError, match="4 cells and 3 boxes"):
        build_table(_region(), structure, [], offset=(0, 0), page_size=PAGE)


def test_a_table_over_the_cap_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "TABLE_MAX_CELLS", 3)
    with pytest.raises(ValueError, match="not read"):
        build_table(_region(), _structure(), [], offset=(0, 0), page_size=PAGE)


def test_a_table_with_nothing_in_it_is_not_to_be_trusted():
    table = build_table(_region(), _structure(), [], offset=(0, 0), page_size=PAGE)
    assert table.score == 0.0 and not table.has_header


def test_a_row_with_nothing_in_it_holds_the_score_down():
    lines = [_line("Année", 10, 10, 90, 40), _line("Total", 110, 10, 190, 40)]
    assert build_table(_region(), _structure(), lines, offset=(0, 0), page_size=PAGE).score == 0.495


def test_the_boxes_stay_on_the_page():
    structure = _structure(1, 1, cell=(3000, 3000))
    box = build_table(_region(), structure, [_line("x", 10, 10, 50, 40)], offset=(0, 0), page_size=PAGE).cells[0].box
    assert (box.x_max, box.y_max) == (1.0, 1.0)


# --- the reader ---


class FakeStructure:
    def __init__(self, answer=None):
        self.answer = answer if answer is not None else [_structure()]
        self.crops = []

    def predict(self, crop):
        self.crops.append(crop)
        return self.answer


class FakeOcr:
    def __init__(self):
        self.crops = []

    def predict(self, crop, return_word_box=False):
        self.crops.append(crop)
        return [
            {
                "rec_texts": ["Année", "Total", "2024", "12"],
                "rec_scores": [0.9] * 4,
                "rec_boxes": np.array([[10, 10, 90, 40], [110, 10, 190, 40], [10, 60, 90, 90], [110, 60, 190, 90]]),
            }
        ]


def _page(width=1000, height=2000) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_only_the_table_regions_are_read_in_reading_order():
    structure, ocr = FakeStructure(), FakeOcr()
    reader = TableReader(lambda: structure, lambda: ocr)
    regions = [
        _region(0, type_=RegionType.TEXT),
        _region(1),
        _region(2, (0.1, 0.5, 0.6, 0.6), RegionType.IMAGE),
        _region(3, (0.1, 0.7, 0.6, 0.8)),
    ]

    page = reader.read(_page(), regions, "doc-1", 4)

    assert (page.document_id, page.page_number) == ("doc-1", 4)
    assert [table.region_order for table in page.tables] == [1, 3]
    assert len(structure.crops) == len(ocr.crops) == 2


def test_a_table_is_read_from_its_crop_with_a_margin_cut_at_the_page(monkeypatch):
    monkeypatch.setattr(settings, "TABLE_CROP_MARGIN_PIXELS", 8)
    crop, offset = crop_table(_page(), _region(box=(0.0, 0.0, 0.5, 0.1)), 8)
    assert offset == (0, 0) and crop.shape == (208, 508, 3)
    crop, offset = crop_table(_page(), _region(box=(0.1, 0.2, 0.6, 0.3)), 8)
    assert offset == (92, 392) and crop.shape == (216, 516, 3)


def test_a_crop_is_a_copy_the_page_is_never_painted():
    page = _page()
    crop, _ = crop_table(page, _region(), 8)
    crop[:] = 255
    assert page.max() == 0


def test_a_region_with_no_area_is_refused():
    with pytest.raises(ValueError, match="empty"):
        crop_table(_page(), _region(box=(0.5, 0.5, 0.5, 0.5)), 0)


def test_a_model_that_reads_nothing_fails_the_page():
    reader = TableReader(lambda: FakeStructure(answer=[]), FakeOcr)
    with pytest.raises(ValueError, match="read nothing"):
        reader.read(_page(), [_region()], "d", 1)


def test_the_tables_of_a_page_are_capped(monkeypatch):
    monkeypatch.setattr(settings, "TABLE_MAX_PER_PAGE", 1)
    reader = TableReader(FakeStructure, FakeOcr)
    page = reader.read(_page(), [_region(0), _region(1, (0.1, 0.5, 0.6, 0.6))], "d", 1)
    assert [table.region_order for table in page.tables] == [0]


def test_a_page_without_table_is_a_valid_empty_result():
    page = TableReader(FakeStructure, FakeOcr).read(_page(), [_region(type_=RegionType.TEXT)], "d", 1)
    assert page.tables == []


def test_the_models_are_loaded_once_for_many_pages_and_not_before_they_are_needed():
    loads = []

    def structure():
        loads.append("structure")
        return FakeStructure()

    def ocr():
        loads.append("ocr")
        return FakeOcr()

    reader = TableReader(structure, ocr)
    assert loads == []
    for number in (1, 2, 3):
        reader.read(_page(), [_region()], "d", number)
    assert sorted(loads) == ["ocr", "structure"]


def test_a_missing_model_fails_with_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODELS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="no table model"):
        tables_module._make_structure()


# --- the task ---


def _png(width=120, height=80) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_task_reads_the_page_from_storage_and_gives_the_tables_in_json(monkeypatch):
    from app import tasks

    asked, seen = [], {}

    class Storage:
        def get_object(self, key):
            asked.append(key)
            return _png()

    class Reader:
        def read(self, image, regions, document_id, page_number):
            seen["shape"], seen["first_pixel_bgr"], seen["types"] = (
                image.shape,
                image[0, 0].tolist(),
                [r.type for r in regions],
            )
            return PageTables(document_id=document_id, page_number=page_number, model_version="fake")

    monkeypatch.setattr(tasks, "storage", Storage())
    monkeypatch.setattr(tasks, "reader", Reader())
    result = tasks.table_regions("doc-1", 2, "ocr-pages/doc-1/page-2.png", [_region().model_dump(mode="json")])
    assert asked == ["ocr-pages/doc-1/page-2.png"]
    # A BGR array: the image's (10, 20, 30) RGB is (30, 20, 10) here.
    assert seen == {"shape": (80, 120, 3), "first_pixel_bgr": [30, 20, 10], "types": [RegionType.TABLE]}
    assert PageTables.model_validate(result).page_number == 2


def test_the_task_is_on_the_table_queue_under_the_name_the_extraction_worker_sends_to():
    from app.celery_app import celery_app

    assert "app.tasks.table_regions" in celery_app.tasks
    assert celery_app.conf.task_default_queue == settings.TABLE_QUEUE_NAME == "document_table"
    [queue] = celery_app.conf.task_queues
    assert queue.exchange.name == queue.routing_key == queue.name == settings.TABLE_QUEUE_NAME


# --- the real models: skipped where they are not (the image of the pod has them) ---

_ROOT = Path(os.environ.get("MODELS_DIR", settings.MODELS_DIR))
_HAVE_MODELS = all(
    (_ROOT / name / "inference.onnx").is_file()
    for name in (settings.TABLE_MODEL_NAME, settings.OCR_DET_MODEL_NAME, settings.OCR_REC_MODEL_NAME)
)
_FONT = next(iter(Path("/usr/share/fonts").rglob("DejaVuSans.ttf")), None)


def _drawn(rows, widths, borders=True) -> np.ndarray:
    from PIL import ImageDraw, ImageFont

    row_h = 70
    image = Image.new("RGB", (sum(widths) + 80, row_h * len(rows) + 80), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(_FONT), 30)
    for r, row in enumerate(rows):
        x, c = 40, 0
        for text, span in row:
            width = sum(widths[c : c + span])
            if borders:
                draw.rectangle([x, 40 + r * row_h, x + width, 40 + (r + 1) * row_h], outline="black", width=3)
            draw.text((x + 16, 40 + r * row_h + 18), text, font=font, fill="black")
            x, c = x + width, c + span
        if not borders and r == 0:
            draw.line([40, 40 + row_h, sum(widths) + 40, 40 + row_h], fill="black", width=3)
    return np.asarray(image)[:, :, ::-1].copy()


def _whole(image) -> Region:
    return _region(0, (0.02, 0.02, 0.98, 0.98))


@pytest.mark.slow
@pytest.mark.skipif(not (_HAVE_MODELS and _FONT), reason=f"no models in {_ROOT}, or no font to draw with")
def test_the_real_models_read_a_bordered_table_with_its_accents_and_amounts():
    rows = [
        [(t, 1) for t in row]
        for row in (
            ("Année", "Dossiers", "Délai (j)", "Coût (€)"),
            ("2023", "1 120", "34", "12 450,00"),
            ("2024", "1 234", "29", "13 980,50"),
        )
    ]
    image = _drawn(rows, [260, 300, 300, 340])
    table = TableReader().read(image, [_whole(image)], "d", 1).tables[0]
    grid = {(c.row, c.col): c.text for c in table.cells}
    assert (table.n_rows, table.n_cols) == (3, 4) and table.has_header and table.score > 0.9
    assert [grid[(0, c)] for c in range(4)] == ["Année", "Dossiers", "Délai (j)", "Coût (€)"]
    assert [grid[(1, c)] for c in range(4)] == ["2023", "1 120", "34", "12 450,00"]
    assert [grid[(2, c)] for c in range(4)] == ["2024", "1 234", "29", "13 980,50"]


@pytest.mark.slow
@pytest.mark.skipif(not (_HAVE_MODELS and _FONT), reason=f"no models in {_ROOT}, or no font to draw with")
def test_the_real_models_read_a_merged_header():
    rows = [
        [("Résultats de l'exercice", 3), ("Observations", 1)],
        [(t, 1) for t in ("Service", "Réalisé", "Prévu", "Remarque")],
        [(t, 1) for t in ("Archives", "120", "100", "Hausse")],
    ]
    image = _drawn(rows, [320, 260, 260, 360])
    table = TableReader().read(image, [_whole(image)], "d", 1).tables[0]
    first = next(c for c in table.cells if (c.row, c.col) == (0, 0))
    assert (first.text, first.col_span) == ("Résultats de l'exercice", 3)
    assert next(c.text for c in table.cells if (c.row, c.col) == (2, 3)) == "Hausse"


@pytest.mark.slow
@pytest.mark.skipif(not (_HAVE_MODELS and _FONT), reason=f"no models in {_ROOT}, or no font to draw with")
def test_the_real_models_doubt_a_borderless_table_they_get_wrong():
    """SLANet_plus read this one with a made-up merged cell and a header over two rows, and scored itself 0.98."""
    rows = [
        [(t, 1) for t in row]
        for row in (
            ("Région", "Habitants", "Superficie"),
            ("Bretagne", "3 340 000", "27 208"),
            ("Normandie", "3 320 000", "29 906"),
            ("Occitanie", "5 940 000", "72 724"),
        )
    ]
    image = _drawn(rows, [360, 340, 340], borders=False)
    table = TableReader().read(image, [_whole(image)], "d", 1).tables[0]
    assert table.score < 0.6
