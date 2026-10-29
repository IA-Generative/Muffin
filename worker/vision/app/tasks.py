from loguru import logger

from app.celery_app import celery_app
from app.contracts import RegionToDescribe
from app.florence import describer
from app.storage import storage


@celery_app.task(name="app.tasks.describe_regions")
def describe_regions(
    document_id: str,
    page_number: int,
    image_key: str,
    regions: list[dict],
    prompt: str | None = None,
    model: str | None = None,
) -> dict:
    """A description of each region (`{"id", "box", "kind"}`, a box between 0 and 1 on the page) of the page image at
    `image_key`, as a PageDescriptions in JSON: by region id, with the model's version and what it cost.

    `prompt` and `model` are what the other engine of the contract takes (a model of the hub, any question): Florence-2
    answers its one task, and says in `model_version` what answered."""
    to_describe = [RegionToDescribe.model_validate(region) for region in regions]
    result = describer.describe(storage.get_object(image_key), to_describe, document_id, page_number)
    logger.info(
        f"Page {page_number} of {document_id}: {len(result.descriptions)} of {len(to_describe)} region(s) described "
        f"in {result.usage.seconds:.1f} s"
    )
    return result.model_dump(mode="json")
