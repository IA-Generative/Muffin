"""The tasks of the OCR pods and the queue of each (see celery_app.py).

The pods are other images: the extraction worker sends their tasks by name, it does not import them."""

from app.config import settings

LAYOUT_PAGE_TASK = "app.tasks.layout_page"
OCR_REGIONS_TASK = "app.tasks.ocr_regions"
TABLE_REGIONS_TASK = "app.tasks.table_regions"
# Reserved: the vision pod comes after the others (#411).
DESCRIBE_REGIONS_TASK = "app.tasks.describe_regions"


def ocr_task_queues() -> dict[str, str]:
    """Task name -> queue. A function, so that it reads the settings as they are when it is called."""
    return {
        LAYOUT_PAGE_TASK: settings.LAYOUT_QUEUE_NAME,
        OCR_REGIONS_TASK: settings.OCR_QUEUE_NAME,
        TABLE_REGIONS_TASK: settings.TABLE_QUEUE_NAME,
        DESCRIBE_REGIONS_TASK: settings.VISION_QUEUE_NAME,
    }
