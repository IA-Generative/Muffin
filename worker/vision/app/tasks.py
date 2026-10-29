from loguru import logger

from app.celery_app import celery_app
from app.config import settings
from app.contracts import RegionToDescribe
from app.florence import describer
from app.hub import get_hub_describer
from app.storage import storage


@celery_app.task(name="app.tasks.describe_regions")
def describe_regions(
    document_id: str,
    page_number: int,
    image_key: str,
    regions: list[dict],
    prompt: str | None = None,
    model: str | None = None,
    usage: dict | None = None,
) -> dict:
    """A description of each region (`{"id", "box", "kind"}`, a box between 0 and 1 on the page) of the page image at
    `image_key`, as a PageDescriptions in JSON: by region id, with the model's version and what it cost.

    `model` chooses who describes: none, or Florence-2's name, is the local model (English, its one task: `prompt` is
    not used); any other is a model of the hub that reads images, asked through the backend with `prompt` (or a
    question of ours for an image or a table) and the `usage` context the consumption is recorded against."""
    to_describe = [RegionToDescribe.model_validate(region) for region in regions]
    page = storage.get_object(image_key)
    if model and model != settings.VISION_MODEL_NAME:
        result = get_hub_describer().describe(page, to_describe, document_id, page_number, model, prompt, usage)
    else:
        result = describer.describe(page, to_describe, document_id, page_number)
    logger.info(
        f"Page {page_number} of {document_id}: {len(result.descriptions)} of {len(to_describe)} region(s) described "
        f"by {result.model_version} in {result.usage.seconds:.1f} s"
    )
    return result.model_dump(mode="json")
