"""The description of the images and tables of a scanned page (#411).

Which regions are described (`select_regions`), by whom - the vision pod for the "local" engine, a model of the hub that
reads images for the "openai" one - and what is written of it: `[Image : ...]` in the page's text, at the image's place
in the reading order, and the end of a table's marker. The descriptions are made while the page is read: the page is
written once, with them. A description that cannot be made never fails the page.

Both engines speak the vision contract (contracts.py): a page image, regions by id, an optional prompt and model - and
descriptions by id, with what they cost."""

import base64
import json
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.config import settings
from app.ocr import crop
from app.ocr.contracts import (
    DescribeUsage,
    PageDescriptions,
    PageLayout,
    RegionDescription,
    RegionToDescribe,
    RegionType,
)

IMAGE_PROMPT = (
    "Décris cette image en une ou deux phrases, en français, de façon factuelle : ce qu'elle montre, et le texte "
    "lisible qu'elle contient. Réponds par la description seule."
)
TABLE_PROMPT = (
    "Décris ce tableau en une ou deux phrases, en français : son sujet, ses colonnes, ce qu'il permet de savoir. "
    "Ne recopie pas ses cellules. Réponds par la description seule."
)


@dataclass(frozen=True)
class CaptionConfig:
    """What the collection chose (its settings' caption_engine and caption_model)."""

    engine: str = "local"
    model: str | None = None

    @classmethod
    def of(cls, collection_settings: dict[str, Any]) -> "CaptionConfig":
        return cls(collection_settings.get("caption_engine") or "local", collection_settings.get("caption_model"))

    @property
    def enabled(self) -> bool:
        return self.engine == "openai" or settings.VISION_POD_ENABLED


def select_regions(layout: PageLayout, table_orders: set[int], budget: int) -> list[RegionToDescribe]:
    """The regions to describe: the images at least CAPTION_MIN_PIXELS on their smaller side, and the tables read as
    tables (`table_orders`) when CAPTION_TABLES; the biggest first when there are more than CAPTION_MAX_PER_PAGE or than
    `budget` (what is left of the document's). In reading order."""
    candidates: list[tuple[float, RegionToDescribe]] = []
    for region in layout.regions:
        is_table = region.type is RegionType.TABLE and region.reading_order in table_orders
        if not (region.type is RegionType.IMAGE or (is_table and settings.CAPTION_TABLES)):
            continue
        width = (region.box.x_max - region.box.x_min) * layout.width_px
        height = (region.box.y_max - region.box.y_min) * layout.height_px
        if min(width, height) < settings.CAPTION_MIN_PIXELS:
            continue
        candidates.append(
            (
                width * height,
                RegionToDescribe(id=region.reading_order, box=region.box, kind="table" if is_table else "image"),
            )
        )
    keep = max(min(settings.CAPTION_MAX_PER_PAGE, budget), 0)
    biggest = sorted(candidates, key=lambda item: item[0], reverse=True)[:keep]
    return sorted((region for _, region in biggest), key=lambda region: region.id)


def clean(text: str) -> str:
    """A description fit for the page's text: on one line, no bracket (they close the block), cut at a word."""
    flat = re.sub(r"\s+", " ", text.replace("[", "(").replace("]", ")")).strip()
    if len(flat) > settings.CAPTION_MAX_CHARS:
        flat = flat[: settings.CAPTION_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return flat


def image_block(description: str) -> str:
    return f"[Image : {description}]"


class ThreadResult:
    """A future in the shape of a Celery AsyncResult, so that the reader waits for both the same way."""

    def __init__(self, future: Future) -> None:
        self._future = future

    @property
    def result(self) -> Any:
        return self._future.exception() or self._future.result()

    def ready(self) -> bool:
        return self._future.done()

    def successful(self) -> bool:
        return self._future.done() and not self._future.cancelled() and self._future.exception() is None

    def revoke(self) -> None:
        self._future.cancel()

    def forget(self) -> None:
        pass


class HubDescriber:
    """The "openai" engine: each region is cropped from the page's image and shown to a chat model of the hub, which
    records the consumption itself (the LLM proxy of the backend)."""

    def __init__(self, backend: Any, model: str | None) -> None:
        self._backend, self._model = backend, model
        self._pool: ThreadPoolExecutor | None = None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def start(
        self, document_id: str, page_number: int, page_png: bytes, regions: list[RegionToDescribe]
    ) -> ThreadResult:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=max(settings.CAPTION_HUB_CONCURRENCY, 1))
        return ThreadResult(self._pool.submit(self.describe, document_id, page_number, page_png, regions))

    def describe(
        self, document_id: str, page_number: int, page_png: bytes, regions: list[RegionToDescribe]
    ) -> PageDescriptions:
        started = time.monotonic()
        model = self._model or self._backend.get_default_vision_model()
        if not model:
            raise RuntimeError("no model of the hub reads images")
        found: list[RegionDescription] = []
        prompt_tokens = completion_tokens = 0
        counted = False
        for region in regions:
            data = base64.b64encode(crop.crop_region(page_png, region.box)).decode()
            answer = self._backend.llm_chat_usage(
                model,
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": TABLE_PROMPT if region.kind == "table" else IMAGE_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
                        ],
                    }
                ],
                settings.CAPTION_HUB_MAX_TOKENS,
            )
            if answer.get("prompt_tokens") is not None:
                counted = True
                prompt_tokens += answer["prompt_tokens"]
                completion_tokens += answer.get("completion_tokens") or 0
            if (answer.get("content") or "").strip():
                found.append(RegionDescription(id=region.id, text=answer["content"]))
        return PageDescriptions(
            document_id=document_id,
            page_number=page_number,
            descriptions=found,
            model_version=model,
            usage=DescribeUsage(
                model=model,
                prompt_tokens=prompt_tokens if counted else None,
                completion_tokens=completion_tokens if counted else None,
                seconds=round(time.monotonic() - started, 3),
            ),
        )


def translate(texts: list[str], backend: Any) -> list[str]:
    """The descriptions of a page in French, by the pipeline's model - one call for the lot. Florence-2 answers in
    English; when there is no model, or the answer is not what was asked, they stay as they are."""
    if not texts or not settings.CAPTION_TRANSLATE:
        return texts
    try:
        model = backend.get_default_chat_model()
        if model is None:
            return texts
        answer = backend.llm_chat(
            model,
            [
                {
                    "role": "system",
                    "content": "Tu traduis en français des descriptions d'images, fidèlement et sans rien ajouter. "
                    "Réponds par un tableau JSON de chaînes, dans le même ordre, et rien d'autre.",
                },
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
            ],
        )
        translated = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip()))
        if (
            isinstance(translated, list)
            and len(translated) == len(texts)
            and all(isinstance(t, str) for t in translated)
        ):
            return [t.strip() or original for t, original in zip(translated, texts, strict=True)]
    except Exception as error:
        logger.warning(f"The descriptions could not be translated, kept as they are: {error}")
    return texts
