"""The markdown of a scanned page, and its positioned lines, from what the pods found: the regions in reading order
(PageLayout) and the lines read in them (PageText).

- a title is a heading (# for the document's title, ## for a section's), a text, a list or a caption a paragraph;
- an image, a formula, a logo, a stamp, a running header, a footer or a page number is in the markdown nowhere;
- the lines come out as liteparse's own `TextItem`s, in the page's units (points, origin at the top left), in the
  order of the markdown - so that `build_text_boxes` finds each of them in the page's text (app/text_boxes.py).

Lines of a paragraph are joined with a blank, never dehyphenated: "peut-" and "être" at the end and the start of two
lines is as likely a compound word as a cut one, and a line that is no longer in the text cannot be placed."""

import re
from collections.abc import Iterable

from liteparse.types import TextItem, WordBox

from app.ocr.contracts import OcrLine, PageLayout, PageText, Region, RegionType

_BULLET = re.compile(r"^\s*[-•·▪●◦*–—]\s+")
DEFAULT_TITLE_LEVEL = 2


def _item(line: OcrLine, text: str, width: float, height: float) -> TextItem:
    box = line.box
    words = [
        WordBox(
            text=word.text,
            x=word.box.x_min * width,
            y=word.box.y_min * height,
            width=(word.box.x_max - word.box.x_min) * width,
            height=(word.box.y_max - word.box.y_min) * height,
        )
        for word in line.words
    ]
    return TextItem(
        text=text,
        x=box.x_min * width,
        y=box.y_min * height,
        width=(box.x_max - box.x_min) * width,
        height=(box.y_max - box.y_min) * height,
        confidence=line.score,
        words=words,
    )


def _blocks(region: Region, lines: list[OcrLine], one_line_each: bool) -> list[tuple[str, list[tuple[OcrLine, str]]]]:
    """The markdown blocks of a region: each its text, and the lines in it with the text each has there."""
    if region.type is RegionType.TITLE:
        level = region.title_level or DEFAULT_TITLE_LEVEL
        text = " ".join(line.text.strip() for line in lines)
        return [("#" * level + " " + text, [(line, line.text.strip()) for line in lines])]
    if one_line_each:
        return [(line.text.strip(), [(line, line.text.strip())]) for line in lines]
    if any(_BULLET.match(line.text) for line in lines):
        items: list[tuple[str, list[tuple[OcrLine, str]]]] = []
        for line in lines:
            stripped = line.text.strip()
            if _BULLET.match(line.text):
                text = _BULLET.sub("", line.text).strip()
                items.append(("- " + text, [(line, text)]))
            elif items:
                # A line without a marker goes on the item before it.
                previous_text, previous_lines = items[-1]
                items[-1] = (previous_text + " " + stripped, [*previous_lines, (line, stripped)])
            else:
                items.append((stripped, [(line, stripped)]))
        # A list is one block: its items on lines of their own.
        return [("\n".join(text for text, _ in items), [pair for _, pairs in items for pair in pairs])]
    return [(" ".join(line.text.strip() for line in lines), [(line, line.text.strip()) for line in lines])]


def assemble(
    layout: PageLayout,
    text: PageText,
    width: float,
    height: float,
    table_orders: Iterable[int] = (),
    markers: dict[int, str] | None = None,
) -> tuple[str, list[TextItem]]:
    """The page's markdown and its lines. `table_orders`: the regions that were tables, read as text (see
    OCR_READ_TABLES_AS_TEXT) - one line of the page to a line of the markdown. `markers`: the tables that were read as
    tables (#410), by region - each is its marker in the markdown, at its place in the reading order, and no line."""
    lines_by_region = {region.region_order: region.lines for region in text.regions}
    flat = set(table_orders)
    tables = markers or {}
    blocks: list[str] = []
    items: list[TextItem] = []
    for region in layout.regions:
        if region.reading_order in tables:
            blocks.append(tables[region.reading_order])
            continue
        lines = [line for line in lines_by_region.get(region.reading_order, []) if line.text.strip()]
        if not lines:
            continue
        if not (region.type.is_text or region.reading_order in flat):
            continue
        for block_text, block_lines in _blocks(region, lines, region.reading_order in flat):
            blocks.append(block_text)
            items.extend(_item(line, shown, width, height) for line, shown in block_lines)
    return "\n\n".join(blocks), items
