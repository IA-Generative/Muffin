"""The positioned text of a page: lines and words with boxes normalized between 0 and 1 (#350)."""

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

from app import parsing, tasks
from app.text_boxes import MAX_LINES, build_text_boxes


def _item(text, x, y, width, height, words=()):
    return SimpleNamespace(text=text, x=x, y=y, width=width, height=height, words=list(words))


def _word(text, x, y, width, height):
    return SimpleNamespace(text=text, x=x, y=y, width=width, height=height)


def _page(text, items, width=200.0, height=100.0):
    return SimpleNamespace(text=text, text_items=items, width=width, height=height)


def test_a_line_and_its_words_are_normalized_against_the_page():
    page = _page(
        "Bonjour tout le monde",
        [
            _item(
                "Bonjour tout le monde",
                20,
                10,
                100,
                20,
                [_word("Bonjour", 20, 10, 40, 20), _word("tout", 65, 10, 25, 20)],
            )
        ],
    )

    (box,) = build_text_boxes(page)

    assert (box["x_min"], box["y_min"], box["x_max"], box["y_max"]) == (0.1, 0.1, 0.6, 0.3)
    assert (box["char_start"], box["char_end"]) == (0, 21)
    assert [(w["text"], w["char_start"], w["char_end"]) for w in box["words"]] == [("Bonjour", 0, 7), ("tout", 8, 12)]
    assert (box["words"][1]["x_min"], box["words"][1]["x_max"]) == (0.325, 0.45)


def test_lines_are_placed_in_the_page_text_in_reading_order():
    page = _page(
        "Un\n\n\nDeux\nUn",
        [_item("Un", 0, 0, 10, 10), _item("Deux", 0, 30, 10, 10), _item("Un", 0, 60, 10, 10)],
    )

    boxes = build_text_boxes(page)

    # The second "Un" is the one after "Deux": each line is looked for after the previous one.
    assert [(box["char_start"], box["char_end"]) for box in boxes] == [(0, 2), (5, 9), (10, 12)]


def test_a_line_that_is_not_in_the_page_text_is_kept_without_an_interval():
    """What OCR can give: the line can be read and placed on the page, not found in its text."""
    (box,) = build_text_boxes(_page("tout autre texte", [_item("Texte OCR", 10, 10, 50, 10)]))

    assert box["char_start"] is None and box["char_end"] is None and box["x_min"] == 0.05


def test_a_box_beyond_the_page_is_brought_back_inside_it():
    (box,) = build_text_boxes(_page("a", [_item("a", -10, 90, 300, 40)]))

    assert (box["x_min"], box["x_max"], box["y_max"]) == (0.0, 1.0, 1.0)


def test_items_without_text_or_area_are_left_out():
    page = _page(
        "a b", [_item("", 0, 0, 10, 10), _item("a", 0, 0, 0, 10), _item("b", 0, 0, 10, 0), _item("a", 5, 5, 5, 5)]
    )

    assert [box["text"] for box in build_text_boxes(page)] == ["a"]


def test_a_page_without_positioned_text_gives_none():
    assert build_text_boxes(SimpleNamespace(text="x", text_items=[], width=100, height=100)) == []
    assert build_text_boxes(SimpleNamespace(text="x")) == []
    assert build_text_boxes(_page("x", [_item("x", 0, 0, 5, 5)], width=0, height=0)) == []


def test_a_page_with_more_lines_than_the_backend_takes_is_cut_not_refused():
    lines = [_item("a", 0, 0, 1, 1) for _ in range(MAX_LINES + 10)]

    assert len(build_text_boxes(_page("a " * (MAX_LINES + 10), lines))) == MAX_LINES


def test_a_file_is_written_page_by_page_with_its_positioned_text(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(tasks._shared, "storage", MagicMock())
    page = SimpleNamespace(
        page_num=1, text="Bonjour", blocks=[], text_items=[_item("Bonjour", 20, 10, 40, 20)], width=200, height=100
    )
    monkeypatch.setattr(tasks._shared, "parse_file", lambda data: SimpleNamespace(pages=[page], screenshots=[]))

    tasks._process_file("doc-1", "docs/a.pdf", b"%PDF", "a.pdf")

    boxes = backend.add_page.call_args.kwargs["text_boxes"]
    assert [box["text"] for box in boxes] == ["Bonjour"] and boxes[0]["x_min"] == 0.1


def _pdf(width, height, lines):
    content = "".join(f"BT /F1 14 Tf {x} {y} Td ({text}) Tj ET\n" for x, y, text in lines).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents 5 0 R "
        "/Resources << /Font << /F1 3 0 R >> >> >>".encode(),
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for number, item in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + item + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return body + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_with_the_real_parser_the_boxes_land_on_the_screenshot_whatever_the_page_format():
    """A landscape and a portrait page: the boxes, normalized, have the screenshot's own proportions - the
    scale it is rendered at does not matter."""
    for width, height in ((300, 200), (200, 300)):
        parser = parsing._make_parser(ocr_enabled=False)
        try:
            result = parser.parse(
                _pdf(width, height, [(20, height - 40, "Bonjour tout le monde"), (20, 40, "Deuxieme ligne")])
            )
        finally:
            parser.close()
        page, screenshot = result.pages[0], result.screenshots[0]
        image_width, image_height = struct.unpack(">II", screenshot.image_bytes[16:24])

        boxes = build_text_boxes(page)

        assert [box["text"] for box in boxes] == ["Bonjour tout le monde", "Deuxieme ligne"]
        top, bottom = boxes
        # The first line is at the top of the page, the second near the bottom, whatever the format.
        assert top["y_min"] < 0.5 < bottom["y_min"]
        assert abs(image_width / image_height - width / height) < 0.01
        # The box is where the text is: 20 points from the left, a line 14 points high or so.
        assert abs(top["x_min"] - 20 / width) < 0.01
        assert 0 < top["y_max"] - top["y_min"] < 0.2
        assert page.text[top["char_start"] : top["char_end"]] == "Bonjour tout le monde"
        assert [word["text"] for word in top["words"]] == ["Bonjour", "tout", "le", "monde"]
        for word in top["words"]:
            assert page.text[word["char_start"] : word["char_end"]] == word["text"]
            assert 0 <= word["x_min"] < word["x_max"] <= 1
