"""Florence-2 base: the description of the crop of a region.

The model is loaded once per process, from MODELS_DIR, with `local_files_only` - nothing is downloaded when the pod
runs. Its code is the one in the image (`trust_remote_code` only lets transformers run the files that sit next to the
weights). Florence-2 answers in English."""

import io
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger
from PIL import Image

from app.config import settings
from app.contracts import (
    DescribeUsage,
    PageDescriptions,
    RegionDescription,
    RegionToDescribe,
)


def crop(page: Image.Image, region: RegionToDescribe, margin: int) -> Image.Image:
    """The region of the page, with a margin, cut at the page's edge."""
    width, height = page.size
    box = region.box
    left, right = max(round(box.x_min * width) - margin, 0), min(round(box.x_max * width) + margin, width)
    top, bottom = max(round(box.y_min * height) - margin, 0), min(round(box.y_max * height) + margin, height)
    return page.crop((left, top, max(right, left + 1), max(bottom, top + 1)))


class _Florence:
    """The real model. Kept apart so that the tests give the reader something else."""

    def __init__(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        path = Path(settings.MODELS_DIR) / settings.VISION_MODEL_NAME
        if settings.TORCH_THREADS:
            torch.set_num_threads(settings.TORCH_THREADS)
        self._torch = torch
        self._processor = AutoProcessor.from_pretrained(path, trust_remote_code=True, local_files_only=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            path, trust_remote_code=True, local_files_only=True, torch_dtype=torch.float32
        ).eval()

    def __call__(self, image: Image.Image) -> str:
        rgb = image.convert("RGB")
        inputs = self._processor(text=settings.VISION_TASK, images=rgb, return_tensors="pt")
        with self._torch.inference_mode():
            generated = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=settings.VISION_MAX_NEW_TOKENS,
                num_beams=settings.VISION_NUM_BEAMS,
                do_sample=False,
                use_cache=False,
            )
        text = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(text, task=settings.VISION_TASK, image_size=rgb.size)
        return str(parsed[settings.VISION_TASK]).strip()


class Describer:
    def __init__(self, model: Callable[[Image.Image], str] | None = None) -> None:
        self._model: Any = model

    def _loaded(self) -> Callable[[Image.Image], str]:
        if self._model is None:
            started = time.monotonic()
            self._model = _Florence()
            logger.info(f"{settings.VISION_MODEL_NAME} loaded in {time.monotonic() - started:.1f} s")
        return self._model

    def describe(
        self, page_png: bytes, regions: list[RegionToDescribe], document_id: str, page_number: int
    ) -> PageDescriptions:
        if len(regions) > settings.VISION_MAX_REGIONS:
            raise ValueError(f"{len(regions)} regions to describe, over the {settings.VISION_MAX_REGIONS} of a page")
        started = time.monotonic()
        model = self._loaded()
        descriptions: list[RegionDescription] = []
        with Image.open(io.BytesIO(page_png)) as page:
            for region in regions:
                text = model(crop(page, region, settings.VISION_CROP_MARGIN_PIXELS))
                if text:
                    descriptions.append(RegionDescription(id=region.id, text=text))
        return PageDescriptions(
            document_id=document_id,
            page_number=page_number,
            descriptions=descriptions,
            model_version=settings.VISION_MODEL_NAME,
            usage=DescribeUsage(model=settings.VISION_MODEL_NAME, seconds=round(time.monotonic() - started, 3)),
        )


describer = Describer()
