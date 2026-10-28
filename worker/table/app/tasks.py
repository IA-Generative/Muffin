import io

import numpy as np
from loguru import logger
from PIL import Image

from app.celery_app import celery_app
from app.contracts import Region
from app.storage import storage
from app.tables import reader


def _decode(data: bytes) -> np.ndarray:
    """The page as a BGR array, as the models' processing expects it."""
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


@celery_app.task(name="app.tasks.table_regions")
def table_regions(document_id: str, page_number: int, image_key: str, regions: list[dict]) -> dict:
    """The tables of a page - their structure and the text of their cells - as a PageTables in JSON. `regions` are the
    regions of the page's layout (a PageLayout's `regions`); only the tables are read. A table that cannot be read fails
    the task: the caller then reads the page another way."""
    page_regions = [Region.model_validate(region) for region in regions]
    image = _decode(storage.get_object(image_key))
    tables = reader.read(image, page_regions, document_id, page_number)
    logger.info(f"Tables of page {page_number} of {document_id}: {len(tables.tables)} read")
    return tables.model_dump(mode="json")
