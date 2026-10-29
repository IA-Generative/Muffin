"""The images and tables of a scanned page, described while it is read (#411): which regions, by which engine, and what
the page's text and the registry keep of it."""

import io
import json

import pytest
from PIL import Image

from app import reuse
from app.config import settings
from app.ocr import describe, routing
from app.ocr.contracts import (
    Box,
    DescribeUsage,
    PageDescriptions,
    PageLayout,
    Region,
    RegionDescription,
    RegionType,
)
from app.ocr.describe import CaptionConfig, select_regions
from app.ocr.regions import regions_of
from app.ocr.scanned import ScannedPageReader
from tests.test_ocr_scanned import Clock, FakeApp, FakeResult, FakeStorage, _pages

BIG = Box(x_min=0.1, y_min=0.3, x_max=0.6, y_max=0.6)


def _png(width=1000, height=1000) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def _layout(*regions: Region) -> PageLayout:
    return PageLayout(
        document_id="d", page_number=1, width_px=1000, height_px=1000, regions=list(regions), model_version="l"
    )


def _image(order: int, box: Box = BIG, score: float = 0.9) -> Region:
    return Region(type=RegionType.IMAGE, score=score, reading_order=order, box=box)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_MIN_PIXELS", 96)
    monkeypatch.setattr(settings, "CAPTION_MAX_PER_PAGE", 5)
    monkeypatch.setattr(settings, "CAPTION_MAX_PER_DOCUMENT", 50)
    monkeypatch.setattr(settings, "CAPTION_TABLES", True)
    monkeypatch.setattr(settings, "CAPTION_TRANSLATE", True)
    monkeypatch.setattr(settings, "VISION_POD_ENABLED", True)


# --- which regions ---


def test_only_the_images_big_enough_are_described():
    small = Box(x_min=0.1, y_min=0.1, x_max=0.15, y_max=0.5)
    selected = select_regions(_layout(_image(0, small), _image(1)), set(), budget=10)
    assert [region.id for region in selected] == [1]
    assert selected[0].kind == "image"


def test_the_biggest_win_when_a_page_has_more_than_its_cap_and_they_come_back_in_reading_order(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_MAX_PER_PAGE", 2)
    wide = Box(x_min=0.0, y_min=0.0, x_max=0.9, y_max=0.9)
    mid = Box(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)
    selected = select_regions(_layout(_image(0, mid), _image(1, BIG), _image(2, wide)), set(), budget=10)
    assert [region.id for region in selected] == [0, 2]


def test_what_is_left_of_the_documents_cap_bounds_a_page():
    assert len(select_regions(_layout(_image(0), _image(1)), set(), budget=1)) == 1
    assert select_regions(_layout(_image(0)), set(), budget=0) == []


def test_a_table_is_described_only_when_it_was_read_as_a_table():
    table = Region(type=RegionType.TABLE, score=0.9, reading_order=0, box=BIG)
    assert select_regions(_layout(table), set(), 10) == []
    assert [(r.id, r.kind) for r in select_regions(_layout(table), {0}, 10)] == [(0, "table")]


def test_the_tables_can_be_left_out(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_TABLES", False)
    table = Region(type=RegionType.TABLE, score=0.9, reading_order=0, box=BIG)
    assert select_regions(_layout(table), {0}, 10) == []


def test_a_description_is_one_line_without_brackets_and_cut_at_a_word(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_MAX_CHARS", 20)
    assert describe.clean("Un  [chat]\nnoir") == "Un (chat) noir"
    assert describe.clean("un très long texte sans fin") == "un très long texte…"


# --- translation ---


class FakeBackend:
    def __init__(self, chat=None, default_model="gpt", vision="gpt-4o"):
        self.chat_answer, self.default_model, self.vision = chat, default_model, vision
        self.chats: list[tuple[str, list]] = []

    def get_default_chat_model(self):
        return self.default_model

    def get_default_vision_model(self):
        return self.vision

    def llm_chat(self, model, messages, max_tokens=None):
        self.chats.append((model, messages))
        if isinstance(self.chat_answer, Exception):
            raise self.chat_answer
        return self.chat_answer

    def llm_chat_usage(self, model, messages, max_tokens=None):
        self.chats.append((model, messages))
        return {"content": f"description {len(self.chats)}", "prompt_tokens": 100, "completion_tokens": 20}


def test_descriptions_are_translated_in_one_call_and_kept_in_order():
    backend = FakeBackend(chat=json.dumps(["un chat", "un chien"]))
    assert describe.translate(["a cat", "a dog"], backend) == ["un chat", "un chien"]
    assert len(backend.chats) == 1


@pytest.mark.parametrize("answer", ["not json", json.dumps(["only one"]), RuntimeError("hub down")])
def test_a_translation_that_fails_leaves_the_english(answer):
    assert describe.translate(["a cat", "a dog"], FakeBackend(chat=answer)) == ["a cat", "a dog"]


def test_without_a_model_or_when_off_nothing_is_asked(monkeypatch):
    backend = FakeBackend(chat="[]", default_model=None)
    assert describe.translate(["a cat"], backend) == ["a cat"]
    monkeypatch.setattr(settings, "CAPTION_TRANSLATE", False)
    assert describe.translate(["a cat"], FakeBackend(chat="x")) == ["a cat"]
    assert backend.chats == []


# --- who is asked ---


def test_the_local_engine_asks_the_pods_own_model_and_the_other_a_model_of_the_hub():
    assert CaptionConfig("local").resolve(FakeBackend()) is None
    assert CaptionConfig("openai", "gpt-4o").resolve(FakeBackend()) == "gpt-4o"
    assert CaptionConfig("openai").resolve(FakeBackend(vision="llava")) == "llava"


def test_no_vision_model_at_all_is_an_error_not_a_made_up_description():
    with pytest.raises(RuntimeError):
        CaptionConfig("openai").resolve(FakeBackend(vision=None))


# --- through the reader ---


class VisionApp(FakeApp):
    """The pods, with the vision one."""

    def __init__(self, descriptions=None, ok=True):
        super().__init__()
        self.described = descriptions
        self.ok = ok

    def send_task(self, name, args):
        if name != routing.DESCRIBE_REGIONS_TASK:
            return super().send_task(name, args)
        self.sent.append((name, args))
        document_id, number, _, regions, prompt, model, usage = args
        self.asked = {"prompt": prompt, "model": model, "usage": usage}
        page = PageDescriptions(
            document_id=document_id,
            page_number=number,
            descriptions=[
                RegionDescription(id=r["id"], text=(self.described or {}).get(r["id"], "a bar chart")) for r in regions
            ],
            model_version=model or "Florence-2-base",
            usage=DescribeUsage(model=model or "Florence-2-base", seconds=1.5),
        )
        result = FakeResult(page.model_dump(mode="json") if self.ok else RuntimeError("pod down"), ok=self.ok)
        self.results.append(result)
        return result


def _reader(app, config=None, backend=None, clock=None):
    clock = clock or Clock()

    return ScannedPageReader(
        app=app, storage=FakeStorage(), clock=clock, sleep=clock.sleep, captions=config, backend=backend
    )


def _read(app, config, backend, number=3):
    read, failed = _reader(app, config, backend).read("doc-1", _pages(number), {number: _png()})
    assert failed == []
    return read[number]


def test_the_local_engine_sends_the_images_to_the_vision_pod_and_the_page_says_what_they_show():
    backend = FakeBackend(chat=json.dumps(["un histogramme"]))
    app = VisionApp()

    page = _read(app, CaptionConfig("local"), backend)

    name, args = app.sent[-1]
    assert name == routing.DESCRIBE_REGIONS_TASK
    assert [region["id"] for region in args[3]] == [2]
    assert page.markdown == "# Titre 3\n\nUn paragraphe\n\n[Image : un histogramme]\n\nA B\n\n1 2"
    assert page.captions == {2: ("un histogramme", "Florence-2-base")}
    kept = {r["type"]: r for r in regions_of(page.layout, page.captions)}
    assert (kept["image"]["caption"], kept["image"]["caption_model"]) == ("un histogramme", "Florence-2-base")
    assert kept["table"]["caption"] is None
    # The description is not text that was read: no positioned line for it.
    assert [item.text for item in page.items] == ["Titre 3", "Un paragraphe", "A B", "1 2"]


def test_a_table_read_as_a_table_gets_its_description_at_the_end_of_its_marker(monkeypatch):
    monkeypatch.setattr(settings, "OCR_READ_TABLES_AS_TEXT", False)
    backend = FakeBackend(chat=json.dumps(["un histogramme", "les ventes par année"]))
    app = VisionApp(descriptions={2: "a chart", 3: "sales per year"})

    page = _read(app, CaptionConfig("local"), backend)

    assert [region["id"] for region in app.sent[-1][1][3]] == [2, 3]
    assert "— les ventes par année]" in page.markdown
    assert page.markdown.count("[Tableau doc-1/p3/t1") == 1
    assert "[Image : un histogramme]" in page.markdown
    assert page.tables[0].marker.endswith("— les ventes par année]")
    assert page.captions[3] == ("les ventes par année", "Florence-2-base")


def test_the_openai_engine_asks_the_pod_for_a_model_of_the_hub_and_keeps_the_french_as_it_comes():
    backend = FakeBackend()
    app = VisionApp(descriptions={2: "Un histogramme des ventes."})

    page = _read(app, CaptionConfig("openai", "gpt-4o"), backend)

    assert app.asked["model"] == "gpt-4o"
    assert "[Image : Un histogramme des ventes.]" in page.markdown
    assert page.captions == {2: ("Un histogramme des ventes.", "gpt-4o")}
    # The hub was asked for French: nothing to translate, and the worker itself calls no model.
    assert backend.chats == []


def test_the_local_engine_asks_the_pods_own_model():
    app = VisionApp()
    _read(app, CaptionConfig("local"), FakeBackend(chat=json.dumps(["x"])))
    assert app.asked["model"] is None


def test_no_vision_model_in_the_hub_leaves_the_page_without_descriptions_but_read():
    app = VisionApp()
    page = _read(app, CaptionConfig("openai"), FakeBackend(vision=None))
    assert routing.DESCRIBE_REGIONS_TASK not in [name for name, _ in app.sent]
    assert page.captions == {} and "[Image" not in page.markdown


@pytest.mark.parametrize("config", [CaptionConfig("local"), CaptionConfig("openai", "gpt-4o")])
def test_nothing_is_described_while_the_pod_is_not_deployed(monkeypatch, config):
    monkeypatch.setattr(settings, "VISION_POD_ENABLED", False)
    app = VisionApp()
    page = _read(app, config, FakeBackend())
    assert routing.DESCRIBE_REGIONS_TASK not in [name for name, _ in app.sent]
    assert "[Image" not in page.markdown and page.captions == {}


def test_without_a_config_the_page_is_read_as_before():
    app = VisionApp()
    page = _read(app, None, FakeBackend())
    assert page.markdown == "# Titre 3\n\nUn paragraphe\n\nA B\n\n1 2"


def test_a_pod_that_fails_leaves_the_page_without_descriptions_but_read():
    page = _read(VisionApp(ok=False), CaptionConfig("local"), FakeBackend(chat="[]"))
    assert page.markdown == "# Titre 3\n\nUn paragraphe\n\nA B\n\n1 2"
    assert page.captions == {}


def test_a_pod_that_is_too_slow_leaves_the_page_without_descriptions_and_is_revoked(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_STAGE_TIMEOUT_SECONDS", 3)
    app = VisionApp()
    original = app.send_task

    def slow(name, args):
        result = original(name, args)
        if name == routing.DESCRIBE_REGIONS_TASK:
            result._after = 10_000
        return result

    app.send_task = slow
    page = _read(app, CaptionConfig("local"), FakeBackend(chat="[]"))
    assert page.captions == {} and "[Image" not in page.markdown
    assert app.results[-1].revoked


def test_the_documents_cap_is_shared_by_its_pages(monkeypatch):
    monkeypatch.setattr(settings, "CAPTION_MAX_PER_DOCUMENT", 1)
    app = VisionApp()
    reader = _reader(app, CaptionConfig("local"), FakeBackend(chat=json.dumps(["x"])))
    read, _ = reader.read("doc-1", _pages(1, 2), {1: _png(), 2: _png()})
    assert len([name for name, _ in app.sent if name == routing.DESCRIBE_REGIONS_TASK]) == 1
    assert sum(1 for page in read.values() if page.captions) == 1


def test_the_collections_settings_say_who_describes():
    assert CaptionConfig.of({}) == CaptionConfig("local", None)
    assert CaptionConfig.of({"caption_engine": "openai", "caption_model": "m"}) == CaptionConfig("openai", "m")


# --- the fingerprint ---


def test_the_extraction_fingerprint_follows_who_describes_the_images(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "layout")
    h = "a" * 64
    monkeypatch.setattr(settings, "VISION_POD_ENABLED", False)
    nobody = reuse.extraction(h, {"caption_engine": "local"})
    assert nobody == reuse.extraction(h)
    monkeypatch.setattr(settings, "VISION_POD_ENABLED", True)
    local = reuse.extraction(h, {"caption_engine": "local"})
    gpt = reuse.extraction(h, {"caption_engine": "openai", "caption_model": "gpt-4o"})
    other = reuse.extraction(h, {"caption_engine": "openai", "caption_model": "llava"})
    assert len({nobody, local, gpt, other}) == 4
    monkeypatch.setattr(settings, "CAPTION_MAX_PER_PAGE", 1)
    assert reuse.extraction(h, {"caption_engine": "local"}) != local


def test_the_default_engine_keeps_the_fingerprints_of_before(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    h = "b" * 64
    assert reuse.extraction(h, {"caption_engine": "openai", "caption_model": "gpt-4o"}) == reuse.extraction(h)
