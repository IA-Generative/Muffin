from loguru import logger

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.sync_owui")
def sync_owui() -> dict:
    """Root of a synchronisation Open WebUI -> Muffin (#453). The tasks that read Open WebUI and write
    Muffin come with the following steps."""
    logger.info("Open WebUI synchronisation requested")
    return {"status": "nothing_to_do"}
