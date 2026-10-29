"""The description of the images and tables of a scanned page (#411).

Which regions are described (`select_regions`), by whom - the vision pod, with its own model for the "local" engine or a
model of the hub that reads images (asked by the pod through the backend) for the "openai" one - and what is written of
it: `[Image : ...]` in the page's text, at the image's place in the reading order, and the end of a table's marker. The
descriptions are made while the page is read: the page is written once, with them. A description that cannot be made
never fails the page.

Both engines are one task of the pod (contracts.py): a page image, regions by id, an optional prompt and model - and
descriptions by id, with what they cost."""

import json
import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.config import settings
from app.ocr.contracts import (
    PageLayout,
    RegionToDescribe,
    RegionType,
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
        # Both engines are the vision pod's: its own model, or a model of the hub it asks through the backend.
        return settings.VISION_POD_ENABLED

    def resolve(self, backend: Any) -> str | None:
        """The `model` the pod is sent: None for its own, the hub's model for the other engine - the collection's, or
        the first of the hub that reads images. Raises when there is none: a description made up is no description."""
        if self.engine != "openai":
            return None
        model = self.model or backend.get_default_vision_model()
        if not model:
            raise RuntimeError("no model of the hub reads images")
        return model


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
