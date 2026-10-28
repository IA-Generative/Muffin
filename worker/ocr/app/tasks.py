import io

import numpy as np
from loguru import logger
from PIL import Image

from app.celery_app import celery_app
from app.contracts import Region
from app.reader import reader
from app.storage import storage


def _decode(data: bytes) -> np.ndarray:
    """The page as a BGR array, as the models' processing expects it."""
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


@celery_app.task(name="app.tasks.ocr_regions")
def ocr_regions(document_id: str, page_number: int, image_key: str, regions: list[dict]) -> dict:
    """The lines and words of the text regions of a page, as a PageText in JSON. `regions` are the regions of the
    page's layout (a PageLayout's `regions`); only the text ones are read, and the others are masked."""
    page_regions = [Region.model_validate(region) for region in regions]
    image = _decode(storage.get_object(image_key))
    text = reader.read(image, page_regions, document_id, page_number)
    lines = sum(len(region.lines) for region in text.regions)
    logger.info(f"OCR of page {page_number} of {document_id}: {lines} line(s) in {len(text.regions)} region(s)")
    return text.model_dump(mode="json")
