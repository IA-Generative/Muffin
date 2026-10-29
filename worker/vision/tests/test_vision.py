"""The vision pod: the crop of a region, the descriptions by id, and the task around them (the model is a fake)."""

import io
import os
from pathlib import Path

import pytest
from PIL import Image

from app import tasks
from app.config import settings
from app.contracts import Box, PageDescriptions, RegionToDescribe
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
