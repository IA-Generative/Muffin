"""The tables read on a scanned page (#410): written out, put in the page as markers, and read by the pods."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import reuse, task_logging, tasks
from app.config import settings
from app.ocr import routing
from app.ocr.assemble import assemble
from app.ocr.contracts import (
    Box,
    OcrLine,
    PageLayout,
    PageTables,
    PageText,
    Region,
    RegionText,
    RegionType,
    TableCell,
    TableStructure,
)
from app.ocr.tables import column_headers, header_rows, render_page, to_html, to_markdown
from tests.test_ocr_scanned import Clock, FakeApp, FakeResult, _images, _pages, _reader

BOX = Box(x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.2)


def _cell(row, col, text="", **spans) -> TableCell:
    return TableCell(row=row, col=col, text=text, **spans)


def _table(order=3, rows=3, cols=2, cells=None, header=True, score=0.95) -> TableStructure:
    cells = cells or [
        _cell(0, 0, "Année"),
        _cell(0, 1, "Dossiers"),
        _cell(1, 0, "2023"),
        _cell(1, 1, "1 120"),
        _cell(2, 0, "2024"),
        _cell(2, 1, "1 234"),
    ]
    return TableStructure(region_order=order, n_rows=rows, n_cols=cols, cells=cells, has_header=header, score=score)


def _layout(*types) -> PageLayout:
    regions = [Region(type=t, score=0.9, reading_order=i, box=BOX) for i, t in enumerate(types)]
    return PageLayout(document_id="d", page_number=3, width_px=100, height_px=100, regions=regions, model_version="l")


def _page_tables(*tables) -> PageTables:
    return PageTables(document_id="d", page_number=3, tables=list(tables), model_version="SLANet_plus_onnx")


# --- written out ---


def test_a_table_is_a_markdown_table_with_its_header():
    assert to_markdown(_table()) == ("| Année | Dossiers |\n| --- | --- |\n| 2023 | 1 120 |\n| 2024 | 1 234 |")


def test_a_table_without_header_gets_the_empty_one_that_markdown_requires():
    table = _table(header=False, rows=2, cells=[_cell(0, 0, "a"), _cell(0, 1, "b"), _cell(1, 0, "c"), _cell(1, 1, "d")])
    assert to_markdown(table) == "|  |  |\n| --- | --- |\n| a | b |\n| c | d |"


def test_what_would_break_a_markdown_row_is_escaped_or_flattened():
    table = _table(rows=1, header=False, cells=[_cell(0, 0, "a|b"), _cell(0, 1, "deux\nlignes  espacées")])
    assert to_markdown(table).splitlines()[2] == "| a\\|b | deux lignes espacées |"


def test_a_cell_that_spans_has_its_text_in_its_first_place_in_markdown_and_says_so_in_html():
    table = _table(
        rows=2,
        cells=[_cell(0, 0, "Résultats", col_span=2), _cell(1, 0, "a"), _cell(1, 1, "b")],
    )
    assert to_markdown(table).splitlines()[0] == "| Résultats |  |"
    html = to_html(table)
    assert '<th colspan="2">Résultats</th>' in html and "<td>a</td><td>b</td>" in html


def test_the_html_has_a_head_when_there_is_a_header_and_escapes_the_text():
    html = to_html(_table(rows=2, cells=[_cell(0, 0, "A<B"), _cell(0, 1, "x"), _cell(1, 0, "1 & 2"), _cell(1, 1, "y")]))
    assert html.splitlines() == [
        "<table>",
        "<thead>",
        "<tr><th>A&lt;B</th><th>x</th></tr>",
        "</thead>",
        "<tbody>",
        "<tr><td>1 &amp; 2</td><td>y</td></tr>",
        "</tbody>",
        "</table>",
    ]


def test_the_html_of_a_table_with_no_header_is_all_body():
    html = to_html(_table(rows=1, header=False, cells=[_cell(0, 0, "a"), _cell(0, 1, "b")]))
    assert "<thead>" not in html and html.count("<tr>") == 1 and "<tbody>" in html


def test_a_row_span_is_said_in_the_html():
    table = _table(rows=2, header=False, cells=[_cell(0, 0, "a", row_span=2), _cell(0, 1, "b"), _cell(1, 1, "c")])
    assert '<td rowspan="2">a</td>' in to_html(table)


# --- the headers ---


def test_a_header_is_one_row_and_a_merged_title_over_the_names_makes_two():
    assert header_rows(_table()) == 1
    assert header_rows(_table(header=False)) == 0
    merged = _table(
        rows=3,
        cols=2,
        cells=[
            _cell(0, 0, "Résultats", col_span=2),
            _cell(1, 0, "Réalisé"),
            _cell(1, 1, "Prévu"),
            _cell(2, 0, "1"),
            _cell(2, 1, "2"),
        ],
    )
    assert header_rows(merged) == 2
    assert column_headers(merged, 2) == ["Résultats / Réalisé", "Résultats / Prévu"]


def test_a_two_row_table_with_a_merged_first_row_keeps_one_header_row():
    """There would be nothing left under a second header row."""
    table = _table(rows=2, cells=[_cell(0, 0, "Titre", col_span=2), _cell(1, 0, "a"), _cell(1, 1, "b")])
    assert header_rows(table) == 1


def test_the_header_of_a_column_is_what_the_header_rows_say_over_it_once():
    assert column_headers(_table(), 1) == ["Année", "Dossiers"]
    assert column_headers(_table(), 0) == ["", ""]


# --- the marker ---


def test_a_table_is_a_marker_that_says_where_it_is_what_its_columns_are_and_how_long_it_is():
    [table] = render_page(
        _layout(RegionType.TEXT, RegionType.TEXT, RegionType.TEXT, RegionType.TABLE),
        _page_tables(_table(3)),
        "doc-1",
        3,
    )
    assert table.marker == "[Tableau doc-1/p3/t1 — colonnes : Année | Dossiers — 2 lignes]"
    assert (table.rank, table.region_order, table.reliable, table.headers) == (1, 3, True, ["Année", "Dossiers"])


def test_a_table_without_header_says_how_many_columns_it_has():
    table = _table(header=False, rows=2, cells=[_cell(0, 0, "a"), _cell(0, 1, "b"), _cell(1, 0, "c"), _cell(1, 1, "d")])
    [rendered] = render_page(
        _layout(RegionType.TABLE), _page_tables(table.model_copy(update={"region_order": 0})), "d", 1
    )
    assert rendered.marker == "[Tableau d/p1/t1 — 2 colonnes — 2 lignes]" and rendered.headers is None


def test_one_row_and_one_column_are_singular():
    table = _table(rows=2, cols=1, cells=[_cell(0, 0, "A"), _cell(1, 0, "1")], order=0)
    [rendered] = render_page(_layout(RegionType.TABLE), _page_tables(table), "d", 1)
    assert rendered.marker == "[Tableau d/p1/t1 — colonnes : A — 1 ligne]"


def test_the_ranks_follow_the_reading_order_not_the_order_the_pod_answered_in():
    layout = _layout(RegionType.TABLE, RegionType.TEXT, RegionType.TABLE)
    tables = render_page(layout, _page_tables(_table(2), _table(0)), "d", 5)
    assert [(t.rank, t.region_order) for t in tables] == [(1, 0), (2, 2)]
    assert tables[1].marker.startswith("[Tableau d/p5/t2 ")


def test_a_doubtful_table_says_so_in_its_marker_and_is_not_reliable(monkeypatch):
    monkeypatch.setattr(settings, "OCR_TABLE_MIN_SCORE", 0.6)
    [bad] = render_page(_layout(RegionType.TABLE), _page_tables(_table(0, score=0.49)), "d", 1)
    [good] = render_page(_layout(RegionType.TABLE), _page_tables(_table(0, score=0.6)), "d", 1)
    assert not bad.reliable and bad.marker.endswith("— structure douteuse]")
    assert good.reliable and "douteuse" not in good.marker


def test_headers_too_long_for_a_marker_are_cut_and_brackets_do_not_close_it():
    cells = [_cell(0, c, f"colonne [{c}] " + "x" * 30) for c in range(12)] + [_cell(1, c, "1") for c in range(12)]
    [rendered] = render_page(_layout(RegionType.TABLE), _page_tables(_table(0, rows=2, cols=12, cells=cells)), "d", 1)
    assert rendered.marker.count("]") == 1 and "…" in rendered.marker and len(rendered.marker) < 400


def test_a_table_the_layout_found_but_the_pod_did_not_read_refuses_the_page():
    """Its content would be in the page nowhere."""
    with pytest.raises(ValueError, match="no table in region"):
        render_page(_layout(RegionType.TABLE, RegionType.TABLE), _page_tables(_table(0)), "d", 1)


def test_a_table_too_big_to_be_kept_refuses_the_page(monkeypatch):
    monkeypatch.setattr("app.ocr.tables.MAX_MARKDOWN_CHARS", 10)
    with pytest.raises(ValueError, match="too big"):
        render_page(_layout(RegionType.TABLE), _page_tables(_table(0)), "d", 1)


def test_a_table_is_sent_to_the_backend_tied_to_its_region_by_its_place_in_the_layout():
    layout = _layout(RegionType.TITLE, RegionType.TABLE, RegionType.TEXT)
    [rendered] = render_page(layout, _page_tables(_table(1)), "d", 3)
    payload = rendered.payload(layout)
    assert (payload["rank"], payload["region_position"], payload["n_rows"], payload["n_cols"]) == (1, 1, 3, 2)
    assert payload["cells"][0] == {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "text": "Année"}
    assert payload["markdown"].startswith("| Année |") and payload["html"].startswith("<table>")
    assert (payload["has_header"], payload["headers"], payload["reliable"], payload["score"]) == (
        True,
        ["Année", "Dossiers"],
        True,
        0.95,
    )
    assert payload["model_version"] == "SLANet_plus_onnx"
    assert "box" not in payload["cells"][0]


# --- in the page ---


def _text(*orders_and_lines) -> PageText:
    return PageText(
        document_id="d",
        page_number=3,
        regions=[
            RegionText(region_order=o, lines=[OcrLine(text=t, score=0.9, box=BOX) for t in lines])
            for o, lines in orders_and_lines
        ],
        model_version="o",
    )


def test_a_table_is_its_marker_in_the_markdown_at_its_place_and_has_no_line():
    layout = _layout(RegionType.TITLE, RegionType.TABLE, RegionType.TEXT)
    text = _text((0, ["Rapport"]), (2, ["Après le tableau"]))
    markdown, items = assemble(layout, text, 600, 800, markers={1: "[Tableau d/p3/t1 — 2 colonnes — 1 ligne]"})
    assert markdown == "## Rapport\n\n[Tableau d/p3/t1 — 2 colonnes — 1 ligne]\n\nAprès le tableau"
    assert [item.text for item in items] == ["Rapport", "Après le tableau"]


# --- read by the pods ---


@pytest.fixture(autouse=True)
def _tables_as_tables(monkeypatch):
    monkeypatch.setattr(settings, "OCR_READ_TABLES_AS_TEXT", False)
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    monkeypatch.setattr(settings, "OCR_STAGE_TIMEOUT_SECONDS", 100)
    monkeypatch.setattr(settings, "OCR_POLL_SECONDS", 1)
    monkeypatch.setattr("app.ocr.scanned.raise_if_revoked", lambda: None)


def test_the_tables_go_to_the_table_pod_and_the_text_to_the_text_pod_at_once():
    app = FakeApp()
    read, failed = _reader(app).read("doc-1", _pages(3), _images(3))

    assert failed == []
    names = [name for name, _ in app.sent]
    assert names == [routing.LAYOUT_PAGE_TASK, routing.OCR_REGIONS_TASK, routing.TABLE_REGIONS_TASK]
    _, ocr_args = app.sent[1]
    _, table_args = app.sent[2]
    # The text pod gets every region - it masks the table itself; the table pod only the tables.
    assert [r["type"] for r in ocr_args[3]] == ["title", "text", "image", "table"]
    assert [r["type"] for r in table_args[3]] == ["table"] and table_args[:3] == ["doc-1", 3, ocr_args[2]]
    page = read[3]
    assert [t.marker for t in page.tables] == ["[Tableau doc-1/p3/t1 — colonnes : Année | Total — 1 ligne]"]
    assert page.markdown == "# Titre 3\n\nUn paragraphe\n\n[Tableau doc-1/p3/t1 — colonnes : Année | Total — 1 ligne]"
    assert all(result.forgotten for result in app.results)


def test_a_page_without_table_does_not_wake_the_table_pod():
    def layout(args):
        regions = [Region(type=RegionType.TEXT, score=0.9, reading_order=0, box=BOX)]
        return FakeResult(
            PageLayout(
                document_id=args[0], page_number=args[1], width_px=10, height_px=10, regions=regions, model_version="l"
            ).model_dump(mode="json")
        )

    def text(args):
        return FakeResult(_text((0, ["Un texte"])).model_dump(mode="json"))

    app = FakeApp(layout=layout, text=text)
    read, _ = _reader(app).read("doc-1", _pages(1), _images(1))
    assert [name for name, _ in app.sent] == [routing.LAYOUT_PAGE_TASK, routing.OCR_REGIONS_TASK]
    assert read[1].tables == []


def test_the_page_waits_for_the_slower_of_the_two_pods():
    def slow_table(args):
        return FakeResult(FakeApp._table(args).result, after=4)

    clock = Clock()
    read, failed = _reader(FakeApp(table=slow_table), clock=clock).read("doc-1", _pages(1), _images(1))
    assert list(read) == [1] and failed == []
    assert clock.now == 1 + 4  # one poll for the layout, four for the tables


@pytest.mark.parametrize("who", ["table", "ocr"])
def test_a_pod_that_fails_fails_the_page_at_once_and_revokes_the_other(who):
    never = lambda args: FakeResult(None, after=10**6)  # noqa: E731
    boom = lambda args: FakeResult(RuntimeError("boom"), ok=False)  # noqa: E731
    app = FakeApp(**{"table": {"table": boom, "text": never}, "ocr": {"table": never, "text": boom}}[who])
    clock = Clock()
    read, failed = _reader(app, clock=clock).read("doc-1", _pages(1), _images(1))

    assert read == {} and failed == [1]
    assert clock.now < 10  # not the timeout: the failure was seen
    slow = app.results[1] if who == "table" else app.results[2]
    assert slow.revoked


def test_a_table_the_pod_did_not_read_falls_the_page_back():
    def forgetful(args):
        return FakeResult(
            PageTables(document_id=args[0], page_number=args[1], tables=[], model_version="t").model_dump(mode="json")
        )

    read, failed = _reader(FakeApp(table=forgetful)).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]


def test_a_table_pod_that_answers_something_else_falls_the_page_back():
    read, failed = _reader(FakeApp(table=lambda args: FakeResult({"tables": "not a list"}))).read(
        "doc-1", _pages(1), _images(1)
    )
    assert read == {} and failed == [1]


def test_a_table_pod_that_takes_too_long_falls_the_page_back_and_what_was_sent_is_revoked():
    app = FakeApp(table=lambda args: FakeResult(None, after=10**6))
    read, failed = _reader(app).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]
    assert app.results[2].revoked


def test_with_tables_read_as_text_the_table_pod_is_never_asked(monkeypatch):
    monkeypatch.setattr(settings, "OCR_READ_TABLES_AS_TEXT", True)
    app = FakeApp()
    read, _ = _reader(app).read("doc-1", _pages(1), _images(1))
    assert routing.TABLE_REGIONS_TASK not in [name for name, _ in app.sent]
    assert read[1].tables == []


# --- sent to the backend ---

DOCUMENT = {"id": "doc-1", "type": "file", "name": "scan.pdf", "storage_key": "docs/scan.pdf", "collection_id": "col-1"}


@pytest.fixture
def backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())
    storage = MagicMock()
    storage.get_object.return_value = b"%PDF-1.4 a scan"
    monkeypatch.setattr(tasks._shared, "storage", storage)
    backend.get_document.return_value = DOCUMENT
    monkeypatch.setattr(tasks._shared, "count_pages", lambda data: 2)
    return backend


def _parsed(number, **extra):
    return SimpleNamespace(page_num=number, text=f"p{number}", text_items=[], width=600, height=800, **extra)


def test_the_tables_of_a_page_are_written_with_it_and_a_page_read_another_way_clears_them(backend, monkeypatch):
    sent = [{"rank": 1, "region_position": 1, "markdown": "| a |"}]
    result = SimpleNamespace(pages=[_parsed(1, layout_tables=sent), _parsed(2)], screenshots=[])
    monkeypatch.setattr(tasks._shared, "parse_file", MagicMock(return_value=result))
    monkeypatch.setattr(tasks._shared, "read_scanned_pages", lambda document_id, data, parsed: parsed)

    tasks.process_document("doc-1")

    calls = {call.kwargs["page_number"]: call.kwargs for call in backend.add_page.call_args_list}
    assert calls[1]["tables"] == sent
    assert calls[2]["tables"] == []


def test_the_client_sends_the_tables_only_when_it_has_them():
    from app.backend_client import BackendClient

    client = BackendClient()
    posted = []
    client._client = MagicMock()
    client._client.post.side_effect = lambda url, json: posted.append(json) or MagicMock()

    client.add_page("d", 1, "text")
    client.add_page("d", 2, "text", tables=[])
    client.add_page("d", 3, "text", tables=[{"rank": 1}])

    assert "tables" not in posted[0] and posted[1]["tables"] == [] and posted[2]["tables"] == [{"rank": 1}]


def test_a_page_read_by_the_pods_carries_its_tables_for_the_backend():
    from app.ocr.scanned import read_scanned_pages
    from tests.test_ocr_scanned import FakeReader, _read, _result, _scan_stats, _shot
    from tests.test_ocr_scanned import _parsed as scanned_page

    layout = _layout(RegionType.TITLE, RegionType.TABLE)
    rendered = render_page(layout, _page_tables(_table(1)), "doc-1", 2)
    page = scanned_page(2, stats=_scan_stats())
    reader = FakeReader(read={2: _read("# Titre", [], layout=layout, tables=rendered)})

    out = read_scanned_pages("doc-1", b"pdf", _result(page, screenshots=[_shot(2, 1654)]), reader)

    [table] = out.pages[0].layout_tables
    assert (table["rank"], table["region_position"]) == (1, 1) and table["markdown"].startswith("| Année |")


# --- the fingerprint (#300) ---


@pytest.mark.parametrize("name, value", [("OCR_TABLE_MIN_SCORE", 0.8)])
def test_what_decides_if_a_table_is_reliable_changes_the_fingerprint(monkeypatch, name, value):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    before = reuse.extraction("a" * 64)
    monkeypatch.setattr(settings, name, value)
    assert reuse.extraction("a" * 64) != before


def test_the_default_engines_fingerprint_does_not_know_the_tables(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    before = reuse.extraction("a" * 64)
    monkeypatch.setattr(settings, "OCR_TABLE_MIN_SCORE", 0.9)
    assert reuse.extraction("a" * 64) == before
