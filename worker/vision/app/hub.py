"""A model of the hub that reads images (any OpenAI-compatible vision model): the other engine of the contract.

Each region is cropped from the page and shown to the model through the backend's LLM proxy (`/api/internal/llm/chat`):
the pod holds no key of the hub, and the backend records the consumption against the `usage` context the caller gave."""

import base64
import io
import time
from typing import Any

import httpx
from PIL import Image

from app.config import settings
from app.contracts import DescribeUsage, PageDescriptions, RegionDescription, RegionToDescribe
from app.florence import crop

IMAGE_PROMPT = (
    "Décris cette image en une ou deux phrases, en français, de façon factuelle : ce qu'elle montre, et le texte "
    "lisible qu'elle contient. Réponds par la description seule."
)
TABLE_PROMPT = (
    "Décris ce tableau en une ou deux phrases, en français : son sujet, ses colonnes, ce qu'il permet de savoir. "
    "Ne recopie pas ses cellules. Réponds par la description seule."
)


def _png_data_url(image: Image.Image) -> str:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


class HubDescriber:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            base_url=settings.BACKEND_API_URL,
            headers={"X-API-Key": settings.WORKER_API_KEY},
            timeout=settings.HUB_TIMEOUT_SECONDS,
        )

    def describe(
        self,
        page_png: bytes,
        regions: list[RegionToDescribe],
        document_id: str,
        page_number: int,
        model: str,
        prompt: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> PageDescriptions:
        """`prompt` replaces the question asked for every region; without it, one for an image and one for a table."""
        if len(regions) > settings.VISION_MAX_REGIONS:
            raise ValueError(f"{len(regions)} regions to describe, over the {settings.VISION_MAX_REGIONS} of a page")
        started = time.monotonic()
        found: list[RegionDescription] = []
        prompt_tokens = completion_tokens = 0
        counted = False
        with Image.open(io.BytesIO(page_png)) as page:
            for region in regions:
                question = prompt or (TABLE_PROMPT if region.kind == "table" else IMAGE_PROMPT)
                url = _png_data_url(crop(page, region, settings.VISION_CROP_MARGIN_PIXELS))
                response = self._client.post(
                    "/api/internal/llm/chat",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": question},
                                    {"type": "image_url", "image_url": {"url": url}},
                                ],
                            }
                        ],
                        "max_tokens": settings.HUB_MAX_TOKENS,
                        "usage": usage,
                    },
                )
                response.raise_for_status()
                answer = response.json()
                if answer.get("prompt_tokens") is not None:
                    counted = True
                    prompt_tokens += answer["prompt_tokens"]
                    completion_tokens += answer.get("completion_tokens") or 0
                if (answer.get("content") or "").strip():
                    found.append(RegionDescription(id=region.id, text=answer["content"].strip()))
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


_hub: HubDescriber | None = None


def get_hub_describer() -> HubDescriber:
    """Built when first needed: a pod that only runs Florence-2 never opens a connection to the backend."""
    global _hub
    if _hub is None:
        _hub = HubDescriber()
    return _hub
