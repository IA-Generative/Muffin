"""The vision pod: the crop of a region, the descriptions by id, and the task around them (the model is a fake)."""

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from app import tasks
from app.config import settings
from app.contracts import Box, DescribeUsage, PageDescriptions, RegionToDescribe
from app.florence import Describer, crop


def _png(width: int = 200, height: int = 100) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def _region(order: int, x0: float, y0: float, x1: float, y1: float) -> RegionToDescribe:
    return RegionToDescribe(id=order, box=Box(x_min=x0, y_min=y0, x_max=x1, y_max=y1))


def test_the_crop_is_the_region_and_its_margin_cut_at_the_edge_of_the_page():
    page = Image.new("RGB", (200, 100))
    assert crop(page, _region(0, 0.25, 0.5, 0.5, 1.0), 8).size == (50 + 16, 50 + 8)
    assert crop(page, _region(0, 0.0, 0.0, 0.0, 0.0), 0).size == (1, 1)


def test_each_region_is_described_by_its_id_and_the_usage_is_told():
    seen: list[tuple[int, int]] = []

    def fake(image: Image.Image) -> str:
        seen.append(image.size)
        return f"image {len(seen)}"

    result = Describer(fake).describe(_png(), [_region(3, 0, 0, 0.5, 0.5), _region(7, 0.5, 0.5, 1, 1)], "doc", 2)

    assert [(d.id, d.text) for d in result.descriptions] == [(3, "image 1"), (7, "image 2")]
    assert result.usage.model == settings.VISION_MODEL_NAME
    assert result.usage.prompt_tokens is None
    assert result.usage.seconds >= 0


def test_a_region_the_model_says_nothing_of_is_absent():
    result = Describer(lambda image: "").describe(_png(), [_region(1, 0, 0, 1, 1)], "doc", 1)
    assert result.descriptions == []


def test_a_page_with_too_many_regions_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "VISION_MAX_REGIONS", 1)
    with pytest.raises(ValueError):
        Describer(lambda image: "x").describe(_png(), [_region(0, 0, 0, 1, 1), _region(1, 0, 0, 1, 1)], "doc", 1)


def test_the_task_reads_the_page_and_answers_a_contract(monkeypatch):
    monkeypatch.setattr(tasks.storage, "get_object", lambda key: _png())
    monkeypatch.setattr(tasks, "describer", Describer(lambda image: "un chat"))

    answer = tasks.describe_regions.run(
        "doc", 4, "ocr-pages/doc/page-4.png", [{"id": 2, "box": {"x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1}}]
    )

    page = PageDescriptions.model_validate(answer)
    assert page.page_number == 4
    assert [(d.id, d.text) for d in page.descriptions] == [(2, "un chat")]


@pytest.mark.slow
def test_the_real_model_describes_an_image():
    if not (Path(os.environ.get("MODELS_DIR", settings.MODELS_DIR)) / settings.VISION_MODEL_NAME).exists():
        pytest.skip("the model is not in MODELS_DIR")
    image = Image.new("RGB", (320, 240), "white")
    out = io.BytesIO()
    image.save(out, format="PNG")
    result = Describer().describe(out.getvalue(), [_region(0, 0, 0, 1, 1)], "doc", 1)
    assert result.descriptions and result.descriptions[0].text


# --- a model of the hub ---


class FakeBackend:
    """The backend's LLM proxy: answers each call, and keeps what it was asked."""

    def __init__(self):
        self.calls: list[dict] = []

    def post(self, url, json):
        self.calls.append({"url": url, **json})

        class Response:
            def raise_for_status(self):
                pass

            def json(_self):
                return {"content": f"réponse {len(self.calls)}", "prompt_tokens": 50, "completion_tokens": 10}

        return Response()


def test_a_model_of_the_hub_is_shown_each_crop_through_the_backend_and_the_usage_is_added_up():
    from app.hub import IMAGE_PROMPT, TABLE_PROMPT, HubDescriber

    backend = FakeBackend()
    regions = [_region(1, 0, 0, 0.5, 0.5), RegionToDescribe(id=2, box=_region(2, 0, 0, 1, 1).box, kind="table")]

    result = HubDescriber(backend).describe(_png(), regions, "doc", 3, "gpt-4o", usage={"step": "caption"})

    assert [(d.id, d.text) for d in result.descriptions] == [(1, "réponse 1"), (2, "réponse 2")]
    assert result.model_version == "gpt-4o" and result.usage.model == "gpt-4o"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (100, 20)
    first = backend.calls[0]
    assert first["url"] == "/api/internal/llm/chat" and first["model"] == "gpt-4o"
    assert first["usage"] == {"step": "caption"}
    assert first["messages"][0]["content"][0]["text"] == IMAGE_PROMPT
    assert first["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert backend.calls[1]["messages"][0]["content"][0]["text"] == TABLE_PROMPT


def test_a_prompt_replaces_the_question_for_every_region():
    from app.hub import HubDescriber

    backend = FakeBackend()
    HubDescriber(backend).describe(_png(), [_region(1, 0, 0, 1, 1)], "doc", 1, "gpt-4o", prompt="Que vois-tu ?")
    assert backend.calls[0]["messages"][0]["content"][0]["text"] == "Que vois-tu ?"


def test_the_task_sends_any_model_but_florence_to_the_hub(monkeypatch):
    seen = {}

    class Hub:
        def describe(self, page, regions, document_id, page_number, model, prompt, usage):
            seen.update(model=model, prompt=prompt, usage=usage)
            return PageDescriptions(
                document_id=document_id,
                page_number=page_number,
                descriptions=[],
                model_version=model,
                usage=DescribeUsage(model=model),
            )

    monkeypatch.setattr(tasks.storage, "get_object", lambda key: _png())
    monkeypatch.setattr(tasks, "get_hub_describer", lambda: Hub())
    monkeypatch.setattr(tasks, "describer", Describer(lambda image: "un chat"))
    box = {"x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1}

    hub = tasks.describe_regions.run("doc", 1, "k", [{"id": 0, "box": box}], "Décris", "gpt-4o", {"step": "x"})
    local = tasks.describe_regions.run("doc", 1, "k", [{"id": 0, "box": box}], None, settings.VISION_MODEL_NAME)

    assert seen == {"model": "gpt-4o", "prompt": "Décris", "usage": {"step": "x"}}
    assert hub["model_version"] == "gpt-4o"
    assert local["descriptions"][0]["text"] == "un chat"
