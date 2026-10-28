import io

import numpy as np
from loguru import logger
from PIL import Image

from app.celery_app import celery_app
from app.layout import detector
from app.storage import storage


def _decode(data: bytes) -> np.ndarray:
    """The page as a BGR array, as the model's processing expects it."""
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


@celery_app.task(name="app.tasks.layout_page")
def layout_page(document_id: str, page_number: int, image_key: str) -> dict:
    """The regions of a page - typed, with their boxes between 0 and 1, in reading order - as a PageLayout in JSON.
    An empty list of regions is a result, not an error: the caller then falls back on the parser's own OCR."""
    image = _decode(storage.get_object(image_key))
    layout = detector.detect(image, document_id, page_number)
    logger.info(f"Layout of page {page_number} of {document_id}: {len(layout.regions)} region(s)")
    return layout.model_dump(mode="json")
