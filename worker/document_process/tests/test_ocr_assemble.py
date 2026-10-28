"""The markdown of a scanned page and its positioned lines (app/ocr/assemble.py)."""

from app.ocr.assemble import assemble
from app.ocr.contracts import Box, OcrLine, OcrWord, PageLayout, PageText, Region, RegionText, RegionType
from app.text_boxes import build_text_boxes

WIDTH, HEIGHT = 595.0, 842.0


def _box(x0=0.1, y0=0.1, x1=0.5, y1=0.12) -> Box:
    return Box(x_min=x0, y_min=y0, x_max=x1, y_max=y1)


def _region(order, type_, level=None, box=None) -> Region:
    return Region(type=type_, score=0.9, reading_order=order, box=box or _box(), title_level=level)


def _line(text, y=0.1, words=True) -> OcrLine:
    pieces = text.split()
    n = max(len(pieces), 1)
    return OcrLine(
        text=text,
        score=0.95,
        box=_box(0.1, y, 0.5, y + 0.02),
        words=[
            OcrWord(text=w, score=0.95, box=_box(0.1 + 0.4 * i / n, y, 0.1 + 0.4 * (i + 1) / n, y + 0.02))
            for i, w in enumerate(pieces)
        ]
        if words
        else [],
    )


def _page(regions, lines_by_order) -> tuple[PageLayout, PageText]:
    layout = PageLayout(
        document_id="d", page_number=1, width_px=1000, height_px=1000, regions=regions, model_version="l"
    )
    text = PageText(
        document_id="d",
        page_number=1,
        regions=[RegionText(region_order=order, lines=lines) for order, lines in lines_by_order.items()],
        model_version="o",
    )
    return layout, text


def test_a_title_is_a_heading_by_its_level_and_a_text_is_a_paragraph():
    layout, text = _page(
        [_region(0, RegionType.TITLE, 1), _region(1, RegionType.TITLE, 2), _region(2, RegionType.TEXT)],
        {
            0: [_line("Rapport annuel")],
            1: [_line("Les résultats")],
            2: [_line("Le service a traité", 0.3), _line("de nombreux dossiers.", 0.32)],
        },
    )
    markdown, _ = assemble(layout, text, WIDTH, HEIGHT)
    assert markdown == "# Rapport annuel\n\n## Les résultats\n\nLe service a traité de nombreux dossiers."


def test_a_title_without_a_level_is_a_section_heading():
    layout, text = _page([_region(0, RegionType.TITLE)], {0: [_line("Sans niveau")]})
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "## Sans niveau"


def test_a_title_on_two_lines_is_one_heading():
    layout, text = _page([_region(0, RegionType.TITLE, 1)], {0: [_line("Rapport annuel"), _line("d'activité", 0.12)]})
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "# Rapport annuel d'activité"


def test_what_is_not_text_is_in_the_markdown_nowhere():
    kinds = [
        RegionType.IMAGE,
        RegionType.FORMULA,
        RegionType.LOGO,
        RegionType.STAMP,
        RegionType.HEADER,
        RegionType.FOOTER,
        RegionType.PAGE_NUMBER,
        RegionType.OTHER,
        RegionType.TABLE,
    ]
    regions = [_region(0, RegionType.TEXT)] + [_region(i + 1, kind) for i, kind in enumerate(kinds)]
    lines = {i: [_line(f"texte de {i}")] for i in range(len(regions))}
    layout, text = _page(regions, lines)
    markdown, items = assemble(layout, text, WIDTH, HEIGHT)
    assert markdown == "texte de 0"
    assert [item.text for item in items] == ["texte de 0"]


def test_the_regions_come_in_reading_order():
    layout, text = _page(
        [_region(0, RegionType.TEXT), _region(1, RegionType.TEXT), _region(2, RegionType.CAPTION)],
        {0: [_line("premier")], 1: [_line("deuxième")], 2: [_line("légende")]},
    )
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "premier\n\ndeuxième\n\nlégende"


def test_a_list_has_its_items_on_lines_of_their_own_and_a_line_without_marker_goes_on_the_item_before():
    layout, text = _page(
        [_region(0, RegionType.TEXT)],
        {0: [_line("• premier point"), _line("suite du premier", 0.12), _line("- second point", 0.14)]},
    )
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "- premier point suite du premier\n- second point"


def test_lines_are_never_dehyphenated():
    layout, text = _page([_region(0, RegionType.TEXT)], {0: [_line("une règle peut-"), _line("être utile", 0.12)]})
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "une règle peut- être utile"


def test_a_region_without_a_line_or_with_blank_ones_is_skipped():
    layout, text = _page(
        [_region(0, RegionType.TEXT), _region(1, RegionType.TEXT), _region(2, RegionType.TEXT)],
        {0: [], 1: [_line("   ")], 2: [_line("seule")]},
    )
    assert assemble(layout, text, WIDTH, HEIGHT)[0] == "seule"


def test_a_page_where_nothing_was_read_is_empty():
    layout, text = _page([_region(0, RegionType.TEXT)], {})
    assert assemble(layout, text, WIDTH, HEIGHT) == ("", [])


def test_a_table_read_as_text_gives_a_line_of_the_markdown_to_each_line_read():
    layout, text = _page([_region(0, RegionType.TABLE)], {0: [_line("Année Dossiers"), _line("2024 1 234", 0.12)]})
    markdown, _ = assemble(layout, text, WIDTH, HEIGHT, table_orders={0})
    assert markdown == "Année Dossiers\n\n2024 1 234"


def test_the_lines_are_in_the_pages_units_with_their_words():
    layout, text = _page([_region(0, RegionType.TEXT)], {0: [_line("Bonjour le monde", 0.2)]})
    [item] = assemble(layout, text, WIDTH, HEIGHT)[1]
    assert item.x == 0.1 * WIDTH and item.y == 0.2 * HEIGHT
    assert round(item.width, 3) == round(0.4 * WIDTH, 3) and round(item.height, 3) == round(0.02 * HEIGHT, 3)
    assert item.confidence == 0.95
    assert [word.text for word in item.words] == ["Bonjour", "le", "monde"]
    assert item.words[0].x == 0.1 * WIDTH


def test_every_line_is_found_in_the_pages_text_in_order():
    """What build_text_boxes needs to place a line: its text, in the page's text, after the one before."""

    class Page:
        width, height = WIDTH, HEIGHT

    layout, text = _page(
        [_region(0, RegionType.TITLE, 1), _region(1, RegionType.TEXT), _region(2, RegionType.TEXT)],
        {
            0: [_line("Rapport")],
            1: [_line("première ligne", 0.3), _line("deuxième ligne", 0.32)],
            2: [_line("• un point", 0.5), _line("• un autre", 0.52)],
        },
    )
    markdown, items = assemble(layout, text, WIDTH, HEIGHT)
    page = Page()
    page.text, page.text_items = markdown, items
    boxes = build_text_boxes(page)
    assert [box["text"] for box in boxes] == ["Rapport", "première ligne", "deuxième ligne", "un point", "un autre"]
    starts = [box["char_start"] for box in boxes]
    assert None not in starts and starts == sorted(starts)
    assert all(markdown[box["char_start"] : box["char_end"]] == box["text"] for box in boxes)
    assert [word["text"] for word in boxes[1]["words"]] == ["première", "ligne"]
    assert all(word["char_start"] is not None for word in boxes[1]["words"])


def test_a_line_without_words_is_still_a_line():
    layout, text = _page([_region(0, RegionType.TEXT)], {0: [_line("sans mots", words=False)]})
    [item] = assemble(layout, text, WIDTH, HEIGHT)[1]
    assert item.text == "sans mots" and item.words == []
