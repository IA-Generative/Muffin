"""The scanned pages sent to the OCR pods, and what comes back (app/ocr/scanned.py)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from liteparse.types import ParsedPage, ParseResult, ScreenshotResult

from app import parsing
from app.config import settings
from app.ocr import pages, routing, scanned
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
from app.ocr.scanned import ReadPage, ScannedPageReader, is_scanned, read_scanned_pages
from app.task_revocation import TaskRevoked

BOX = Box(x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.2)


@pytest.fixture(autouse=True)
def _layout_engine(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    monkeypatch.setattr(settings, "OCR_PAGE_WINDOW", 4)
    monkeypatch.setattr(settings, "OCR_STAGE_TIMEOUT_SECONDS", 100)
    monkeypatch.setattr(settings, "OCR_POLL_SECONDS", 1)
    monkeypatch.setattr(settings, "OCR_PAGE_DPI", 200)
    monkeypatch.setattr(scanned, "raise_if_revoked", lambda: None)


# --- which pages are scanned ---


def _stats(**fields):
    base = dict(
        is_garbled=False,
        reasons=[],
        text_length=500,
        full_page_image=False,
        has_substantial_images=False,
        image_block_count=0,
    )
    return SimpleNamespace(**{**base, **fields})


def _parsed(number, text="", stats=None, width=595.0, height=842.0) -> ParsedPage:
    page = ParsedPage(page_num=number, width=width, height=height, text=text)
    page.complexity = stats
    return page


def test_a_page_liteparse_says_was_scanned_is_scanned():
    assert is_scanned(_parsed(1, stats=_stats(reasons=["scanned"], text_length=0, full_page_image=True)))


def test_a_page_with_garbled_text_is_scanned():
    assert is_scanned(_parsed(1, "ðÿþ", stats=_stats(is_garbled=True)))


def test_a_page_with_almost_no_text_and_images_is_scanned():
    assert is_scanned(_parsed(1, "3", stats=_stats(text_length=1, image_block_count=2)))
    assert is_scanned(_parsed(1, "3", stats=_stats(text_length=1, has_substantial_images=True)))


def test_a_blank_page_is_not_scanned():
    assert not is_scanned(_parsed(1, stats=_stats(text_length=0)))


def test_a_sparse_native_page_is_not_scanned_whatever_liteparse_says_of_its_text():
    """liteparse flags 'sparse-text' on a title page: it has its text, there is nothing to read."""
    assert not is_scanned(_parsed(1, "Bonjour " * 30, stats=_stats(reasons=["sparse-text"], text_length=240)))


def test_a_page_with_text_is_not_scanned():
    assert not is_scanned(_parsed(1, "du texte", stats=_stats()))


def test_without_signals_a_page_with_no_text_is_scanned_and_one_with_text_is_not():
    assert is_scanned(_parsed(1, ""))
    assert not is_scanned(_parsed(1, "Un texte natif d'assez de caractères"))


# --- the pods, played ---


class FakeResult:
    """A Celery result: ready after `after` looks at it."""

    def __init__(self, value=None, ok=True, after=0):
        self._value, self._ok, self._after = value, ok, after
        self.revoked = self.forgotten = False

    def ready(self):
        if self._after > 0:
            self._after -= 1
            return False
        return True

    def successful(self):
        return self._ok

    @property
    def result(self):
        return self._value

    def revoke(self):
        self.revoked = True

    def forget(self):
        self.forgotten = True


class FakeApp:
    def __init__(self, layout=None, text=None, table=None):
        self.layout, self.text, self.table = layout or self._layout, text or self._text, table or self._table
        self.sent: list[tuple[str, list]] = []
        self.results: list[FakeResult] = []
        self.in_flight = 0
        self.most_in_flight = 0

    def send_task(self, name, args):
        self.sent.append((name, args))
        handler = {
            routing.LAYOUT_PAGE_TASK: self.layout,
            routing.OCR_REGIONS_TASK: self.text,
            routing.TABLE_REGIONS_TASK: self.table,
        }[name]
        result = handler(args)
        self.results.append(result)
        return result

    @staticmethod
    def _table(args):
        """A 2 x 2 table, with a header, for each region the pod was sent."""
        document_id, number, _, regions = args
        cells = [
            TableCell(row=0, col=0, text="Année"),
            TableCell(row=0, col=1, text="Total"),
            TableCell(row=1, col=0, text="2024"),
            TableCell(row=1, col=1, text="12"),
        ]
        tables = [
            TableStructure(
                region_order=region["reading_order"], n_rows=2, n_cols=2, cells=cells, has_header=True, score=0.95
            )
            for region in regions
        ]
        page = PageTables(document_id=document_id, page_number=number, tables=tables, model_version="t")
        return FakeResult(page.model_dump(mode="json"))

    @staticmethod
    def _layout(args):
        document_id, number, _ = args
        regions = [
            Region(type=RegionType.TITLE, score=0.9, reading_order=0, box=BOX, title_level=1),
            Region(type=RegionType.TEXT, score=0.9, reading_order=1, box=BOX),
            Region(type=RegionType.IMAGE, score=0.9, reading_order=2, box=BOX),
            Region(type=RegionType.TABLE, score=0.9, reading_order=3, box=BOX),
        ]
        layout = PageLayout(
            document_id=document_id, page_number=number, width_px=1000, height_px=1000, regions=regions,
            model_version="l",
        )  # fmt: skip
        return FakeResult(layout.model_dump(mode="json"))

    @staticmethod
    def _text(args):
        document_id, number, _, regions = args
        lines = lambda *texts: [OcrLine(text=t, score=0.9, box=BOX) for t in texts]  # noqa: E731
        text = PageText(
            document_id=document_id,
            page_number=number,
            regions=[
                RegionText(region_order=0, lines=lines(f"Titre {number}")),
                RegionText(region_order=1, lines=lines("Un paragraphe")),
                RegionText(region_order=3, lines=lines("A B", "1 2")),
            ],
            model_version="o",
        )
        return FakeResult(text.model_dump(mode="json"))


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, key, data, content_type=""):
        self.objects[key] = data

    def delete_objects(self, keys):
        for key in keys:
            self.objects.pop(key, None)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _reader(app, storage=None, clock=None):
    clock = clock or Clock()
    return ScannedPageReader(app=app, storage=storage or FakeStorage(), clock=clock, sleep=clock.sleep)


def _pages(*numbers):
    return [_parsed(n) for n in numbers]


def _images(*numbers):
    return {n: f"png-{n}".encode() for n in numbers}


def test_a_page_goes_to_the_layout_pod_then_its_regions_to_the_ocr_pod_and_comes_back_as_markdown():
    app, storage = FakeApp(), FakeStorage()
    read, failed = _reader(app, storage).read("doc-1", _pages(3), _images(3))

    assert failed == []
    markdown, items = read[3].markdown, read[3].items
    assert markdown == "# Titre 3\n\nUn paragraphe\n\nA B\n\n1 2"
    assert [item.text for item in items] == ["Titre 3", "Un paragraphe", "A B", "1 2"]
    key = pages.page_image_key("doc-1", 3)
    assert storage.objects == {key: b"png-3"}
    (layout_name, layout_args), (ocr_name, ocr_args) = app.sent
    assert (layout_name, layout_args) == (routing.LAYOUT_PAGE_TASK, ["doc-1", 3, key])
    assert (ocr_name, ocr_args[:3]) == (routing.OCR_REGIONS_TASK, ["doc-1", 3, key])
    # The regions are the layout's, the table among them read as text since nothing reads tables yet.
    assert [region["type"] for region in ocr_args[3]] == ["title", "text", "image", "text"]
    assert all(result.forgotten for result in app.results)


def test_a_table_stays_a_table_when_it_is_no_longer_read_as_text(monkeypatch):
    monkeypatch.setattr(settings, "OCR_READ_TABLES_AS_TEXT", False)
    app = FakeApp()
    _reader(app).read("doc-1", _pages(1), _images(1))
    assert [region["type"] for region in app.sent[1][1][3]] == ["title", "text", "image", "table"]


def test_the_pods_get_at_most_a_window_of_pages_at_a_time(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PAGE_WINDOW", 2)
    app = FakeApp()
    live = {"now": 0, "most": 0}
    original_layout, original_text = FakeApp._layout, FakeApp._text

    # A page is in the pods' hands from its layout being sent to its text being sent.
    def layout(args):
        live["now"] += 1
        live["most"] = max(live["most"], live["now"])
        return original_layout(args)

    def text(args):
        live["now"] -= 1
        return original_text(args)

    app.layout, app.text = layout, text
    read, failed = _reader(app).read("doc-1", _pages(1, 2, 3, 4, 5), _images(1, 2, 3, 4, 5))
    assert sorted(read) == [1, 2, 3, 4, 5] and failed == []
    assert live["most"] <= 2


def test_a_slow_pod_is_waited_for_not_blocked_on():
    app = FakeApp(layout=lambda args: FakeResult(FakeApp._layout(args).result, after=3))
    clock = Clock()
    read, failed = _reader(app, clock=clock).read("doc-1", _pages(1), _images(1))
    assert list(read) == [1] and failed == []
    # Three polls for the layout, then one for the text: a second each.
    assert clock.now == 4


@pytest.mark.parametrize(
    "app, why",
    [
        (FakeApp(layout=lambda args: FakeResult(RuntimeError("model gone"), ok=False)), "layout step failed"),
        (FakeApp(text=lambda args: FakeResult(ValueError("no image"), ok=False)), "ocr step failed"),
        (FakeApp(layout=lambda args: FakeResult({"unexpected": True})), "unexpected"),
        (FakeApp(text=lambda args: FakeResult({"document_id": 1})), "unexpected"),
    ],
)
def test_a_pod_that_fails_or_answers_something_else_gives_a_page_that_falls_back(app, why, caplog):
    messages = []
    from loguru import logger

    sink = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        read, failed = _reader(app).read("doc-1", _pages(1, 2), _images(1, 2))
    finally:
        logger.remove(sink)
    assert read == {} and sorted(failed) == [1, 2]
    assert any(why in message for message in messages)


def test_a_page_with_no_region_falls_back():
    empty = lambda args: FakeResult(  # noqa: E731
        PageLayout(document_id="d", page_number=args[1], width_px=10, height_px=10, model_version="l").model_dump(
            mode="json"
        )
    )
    read, failed = _reader(FakeApp(layout=empty)).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]


def test_a_page_where_nothing_was_read_falls_back():
    blind = lambda args: FakeResult(  # noqa: E731
        PageText(
            document_id="d", page_number=args[1], regions=[RegionText(region_order=1, lines=[])], model_version="o"
        ).model_dump(mode="json")
    )
    read, failed = _reader(FakeApp(text=blind)).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]


def test_a_page_that_takes_too_long_falls_back_and_what_was_sent_is_revoked():
    app = FakeApp(layout=lambda args: FakeResult(None, after=10**6))
    clock = Clock()
    read, failed = _reader(app, clock=clock).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]
    assert app.results[0].revoked
    assert clock.now > settings.OCR_STAGE_TIMEOUT_SECONDS


def test_one_bad_page_does_not_stop_the_others():
    def layout(args):
        return FakeResult(RuntimeError("boom"), ok=False) if args[1] == 2 else FakeApp._layout(args)

    read, failed = _reader(FakeApp(layout=layout)).read("doc-1", _pages(1, 2, 3), _images(1, 2, 3))
    assert sorted(read) == [1, 3] and failed == [2]


def test_a_page_without_image_or_that_cannot_be_sent_falls_back():
    app = FakeApp()
    read, failed = _reader(app).read("doc-1", _pages(1, 2), _images(1))
    assert list(read) == [1] and failed == [2]

    class Down(FakeStorage):
        def put_object(self, key, data, content_type=""):
            raise OSError("storage down")

    read, failed = _reader(FakeApp(), Down()).read("doc-1", _pages(1), _images(1))
    assert read == {} and failed == [1]


def test_a_revoked_task_revokes_what_it_sent_and_stops(monkeypatch):
    app = FakeApp(layout=lambda args: FakeResult(None, after=10**6))
    calls = {"n": 0}

    def revoked():
        calls["n"] += 1
        if calls["n"] > 2:
            raise TaskRevoked()

    monkeypatch.setattr(scanned, "raise_if_revoked", revoked)
    with pytest.raises(TaskRevoked):
        _reader(app).read("doc-1", _pages(1, 2), _images(1, 2))
    assert len(app.results) == 2 and all(result.revoked for result in app.results)


# --- the file ---


def _result(*page_list, screenshots=None) -> ParseResult:
    return ParseResult(pages=list(page_list), text="", total_pages=len(page_list), screenshots=screenshots or [])


def _scan_stats():
    return _stats(reasons=["scanned"], text_length=0, full_page_image=True)


def _read(markdown, items=None, regions=None, layout=None, tables=None) -> ReadPage:
    """A page the pods read, with a layout of its own."""
    layout = layout or PageLayout(
        document_id="doc-1", page_number=1, width_px=100, height_px=100, regions=regions or [], model_version="l"
    )
    return ReadPage(markdown, items if items is not None else [], layout, tables or [])


class FakeReader:
    def __init__(self, read=None, failed=None, error=None):
        self._read, self._failed, self._error = read or {}, failed or [], error
        self.asked = None

    def read(self, document_id, scanned_pages, images):
        self.asked = (document_id, [p.page_num for p in scanned_pages], images)
        if self._error:
            raise self._error
        return self._read, self._failed


@pytest.fixture
def storage(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.storage.storage", fake)
    return fake


def _shot(number, width):
    return ScreenshotResult(page_num=number, width=width, height=int(width * 1.414), image_bytes=b"shot-%d" % number)


def test_with_the_default_engine_nothing_is_touched(monkeypatch, storage):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    result = _result(_parsed(1, stats=_scan_stats()))
    reader = FakeReader()
    assert read_scanned_pages("doc-1", b"pdf", result, reader) is result
    assert reader.asked is None


def test_a_file_with_no_scanned_page_is_given_back_as_it_is(storage):
    result = _result(_parsed(1, "du texte natif", stats=_stats()))
    reader = FakeReader()
    assert read_scanned_pages("doc-1", b"pdf", result, reader) is result
    assert reader.asked is None


def test_the_scanned_pages_are_replaced_and_the_others_kept(storage):
    native, scan = _parsed(1, "natif", stats=_stats()), _parsed(2, stats=_scan_stats())
    result = _result(native, scan, screenshots=[_shot(2, 1654)])
    reader = FakeReader(read={2: _read("# Lu par les pods", ["item"])})

    out = read_scanned_pages("doc-1", b"pdf", result, reader)

    assert out.pages[0] is native
    assert (out.pages[1].page_num, out.pages[1].text, out.pages[1].text_items) == (2, "# Lu par les pods", ["item"])
    assert (out.pages[1].width, out.pages[1].height) == (595.0, 842.0)
    assert out.screenshots == result.screenshots
    assert reader.asked == ("doc-1", [2], {2: b"shot-2"})


def test_a_screenshot_sharp_enough_is_used_and_a_blurry_one_is_rendered_again(monkeypatch, storage):
    render = MagicMock(return_value={3: (b"rendered-3", 1654, 2339)})
    monkeypatch.setattr(parsing, "render_pages", render)
    pages_ = [_parsed(n, stats=_scan_stats()) for n in (2, 3)]
    # 200 DPI of a 595 pt page is 1654 px: 1654 is sharp enough, 1240 (150 DPI) is not.
    result = _result(*pages_, screenshots=[_shot(2, 1654), _shot(3, 1240)])
    reader = FakeReader(read={2: _read("a"), 3: _read("b")})

    read_scanned_pages("doc-1", b"pdf", result, reader)

    render.assert_called_once_with(b"pdf", [3])
    assert reader.asked[2] == {2: b"shot-2", 3: b"rendered-3"}


def test_the_pages_that_could_not_be_read_fall_back_on_tesseract(monkeypatch, storage):
    fallback = MagicMock(return_value=_result(_parsed(3, "lu par Tesseract")))
    monkeypatch.setattr(parsing, "tesseract_pages", fallback)
    result = _result(
        _parsed(2, stats=_scan_stats()), _parsed(3, stats=_scan_stats()), screenshots=[_shot(2, 1654), _shot(3, 1654)]
    )
    reader = FakeReader(read={2: _read("lu par les pods")}, failed=[3])

    out = read_scanned_pages("doc-1", b"pdf", result, reader)

    fallback.assert_called_once_with(b"pdf", [3])
    assert [page.text for page in out.pages] == ["lu par les pods", "lu par Tesseract"]


def test_the_pages_images_are_dropped_when_it_is_over_and_when_it_fails(storage):
    result = _result(
        _parsed(2, stats=_scan_stats()), _parsed(5, stats=_scan_stats()), screenshots=[_shot(2, 1654), _shot(5, 1654)]
    )
    read_scanned_pages("doc-1", b"pdf", result, FakeReader(read={2: _read("a"), 5: _read("b")}))
    keys = [pages.page_image_key("doc-1", 2), pages.page_image_key("doc-1", 5)]
    storage.delete_objects.assert_called_once_with(keys)

    storage.reset_mock()
    with pytest.raises(TaskRevoked):
        read_scanned_pages("doc-1", b"pdf", result, FakeReader(error=TaskRevoked()))
    storage.delete_objects.assert_called_once_with(keys)


def test_a_failure_to_drop_the_images_does_not_fail_the_file(storage):
    storage.delete_objects.side_effect = OSError("storage down")
    result = _result(_parsed(2, stats=_scan_stats()), screenshots=[_shot(2, 1654)])
    out = read_scanned_pages("doc-1", b"pdf", result, FakeReader(read={2: _read("a")}))
    assert out.pages[0].text == "a"


def test_a_fallback_that_fails_fails_the_file(monkeypatch, storage):
    monkeypatch.setattr(parsing, "tesseract_pages", MagicMock(side_effect=RuntimeError("tesseract gone")))
    result = _result(_parsed(2, stats=_scan_stats()), screenshots=[_shot(2, 1654)])
    with pytest.raises(RuntimeError, match="tesseract gone"):
        read_scanned_pages("doc-1", b"pdf", result, FakeReader(failed=[2]))
