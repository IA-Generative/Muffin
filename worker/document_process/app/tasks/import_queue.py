"""The sweep of the windows of the ZIP imports (#335).

The end of an extraction, an error, a cancellation or a deletion each frees a place in the window of a
document's import and releases the next document. This task, sent by the beat every few minutes, asks the
backend to release whatever those did not - a call lost between two pods, a document whose task vanished
and whose place times out - so that an import never waits for ever with documents left.
"""

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared


@celery_app.task(name="app.tasks.release_import_queue")
def release_import_queue() -> int:
    released = _shared.backend_client.release_import_queue()
    if released:
        logger.info(f"Import queue: {released} document(s) released by the sweep")
    return released
