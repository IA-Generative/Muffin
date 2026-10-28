"""The contracts the OCR pods exchange (app/ocr/contracts.py)."""

import pytest
from pydantic import ValidationError

from app.ocr.contracts import (
    SCHEMA_VERSION,
    Box,
    PageLayout,
    PageTables,
    PageText,
    Region,
    RegionType,
    TableCell,
    TableStructure,
)

BOX = {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.4}


def _region(order: int, type_: str = "text", **extra) -> dict:
    return {"type": type_, "score": 0.9, "reading_order": order, "box": BOX, **extra}


def _layout(regions: list[dict], **extra) -> dict:
    return {
        "document_id": "doc",
        "page_number": 1,
        "width_px": 1654,
        "height_px": 2339,
        "regions": regions,
        "model_version": "layout-1",
        **extra,
    }


def test_a_layout_round_trips_through_json():
    layout = PageLayout.model_validate(_layout([_region(0, "title"), _region(1, "table", polygon=[(0, 0), (1, 1)])]))
    again = PageLayout.model_validate_json(layout.model_dump_json())
    assert again == layout
    assert again.schema_version == SCHEMA_VERSION
    assert [region.type for region in again.regions] == [RegionType.TITLE, RegionType.TABLE]


def test_a_page_without_region_is_a_valid_layout():
    assert PageLayout.model_validate(_layout([])).regions == []


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_box_stays_between_0_and_1(bad):
    with pytest.raises(ValidationError):
        Box(x_min=bad, y_min=0, x_max=1, y_max=1)
    with pytest.raises(ValidationError):
        Box(x_min=0, y_min=0, x_max=bad, y_max=1)


def test_a_box_minimum_cannot_be_past_its_maximum():
    with pytest.raises(ValidationError):
        Box(x_min=0.6, y_min=0, x_max=0.5, y_max=1)
    with pytest.raises(ValidationError):
        Box(x_min=0, y_min=0.6, x_max=1, y_max=0.5)


def test_a_region_needs_a_known_type_and_a_score_between_0_and_1():
    with pytest.raises(ValidationError):
        Region.model_validate(_region(0, "banner"))
    with pytest.raises(ValidationError):
        Region.model_validate({**_region(0), "score": 1.5})
    with pytest.raises(ValidationError):
        Region.model_validate({**_region(0), "reading_order": -1})


def test_two_regions_cannot_share_a_reading_order():
    with pytest.raises(ValidationError, match="share a reading order"):
        PageLayout.model_validate(_layout([_region(0), _region(0, "image")]))


def test_the_regions_come_in_reading_order():
    with pytest.raises(ValidationError, match="reading order"):
        PageLayout.model_validate(_layout([_region(1), _region(0)]))


def test_a_page_has_a_size_and_a_number():
    with pytest.raises(ValidationError):
        PageLayout.model_validate(_layout([], page_number=0))
    with pytest.raises(ValidationError):
        PageLayout.model_validate(_layout([], width_px=0))


def test_a_reader_ignores_the_fields_it_does_not_know():
    """A pod updated before the others adds a field: the others carry on."""
    payload = _layout([{**_region(0), "language": "fr"}], dpi=300)
    layout = PageLayout.model_validate(payload)
    assert not hasattr(layout, "dpi") and not hasattr(layout.regions[0], "language")


def test_a_reader_refuses_a_newer_schema_version():
    with pytest.raises(ValidationError, match="newer"):
        PageLayout.model_validate(_layout([], schema_version=SCHEMA_VERSION + 1))


def test_a_reader_takes_an_older_schema_version():
    assert PageLayout.model_validate(_layout([], schema_version=0)).schema_version == 0


def test_the_types_say_what_becomes_of_a_region():
    text = {t for t in RegionType if t.is_text}
    crops = {t for t in RegionType if t.is_kept_as_crop}
    dropped = {t for t in RegionType if t.is_dropped}
    assert text == {RegionType.TEXT, RegionType.TITLE, RegionType.LIST, RegionType.CAPTION}
    assert crops == {RegionType.TABLE, RegionType.IMAGE, RegionType.FORMULA, RegionType.LOGO, RegionType.STAMP}
    assert dropped == {RegionType.HEADER, RegionType.FOOTER, RegionType.PAGE_NUMBER}
    # Each type has one fate at most; OTHER is read nor kept nor dropped (the assembler decides).
    assert not (text & crops) and not (text & dropped) and not (crops & dropped)
    assert RegionType.OTHER not in text | crops | dropped


def test_a_page_text_carries_lines_and_words_in_the_page_frame():
    line = {
        "text": "Bonjour le monde",
        "score": 0.98,
        "box": BOX,
        "words": [{"text": "Bonjour", "score": 0.99, "box": BOX}],
    }
    text = PageText.model_validate(
        {
            "document_id": "doc",
            "page_number": 2,
            "regions": [{"region_order": 0, "lines": [line]}],
            "model_version": "ocr-1",
        }
    )
    assert text.regions[0].lines[0].words[0].text == "Bonjour"
    assert PageText.model_validate_json(text.model_dump_json()) == text


def test_the_words_of_a_line_are_optional():
    line = {"text": "x", "score": 0.5, "box": BOX}
    text = PageText.model_validate(
        {"document_id": "d", "page_number": 1, "regions": [{"region_order": 0, "lines": [line]}], "model_version": "m"}
    )
    assert text.regions[0].lines[0].words == []


def _table(cells: list[dict], rows: int = 2, cols: int = 2) -> dict:
    return {"region_order": 3, "n_rows": rows, "n_cols": cols, "cells": cells, "score": 0.8}


def test_a_table_holds_its_cells():
    table = TableStructure.model_validate(
        _table([{"row": 0, "col": 0, "col_span": 2, "text": "Total"}, {"row": 1, "col": 1, "text": "12"}])
    )
    assert table.cells[0].row_span == 1 and table.cells[0].col_span == 2
    page = PageTables.model_validate(
        {"document_id": "d", "page_number": 1, "tables": [table.model_dump()], "model_version": "t-1"}
    )
    assert PageTables.model_validate_json(page.model_dump_json()) == page


@pytest.mark.parametrize(
    "cell",
    [
        {"row": 2, "col": 0},
        {"row": 0, "col": 2},
        {"row": 1, "col": 0, "row_span": 2},
        {"row": 0, "col": 1, "col_span": 2},
    ],
)
def test_a_cell_cannot_go_out_of_its_table(cell):
    with pytest.raises(ValidationError, match="out of the table"):
        TableStructure.model_validate(_table([cell]))


def test_a_cell_spans_at_least_one_row_and_one_column():
    with pytest.raises(ValidationError):
        TableCell(row=0, col=0, row_span=0)
    with pytest.raises(ValidationError):
        TableCell(row=0, col=0, col_span=0)
