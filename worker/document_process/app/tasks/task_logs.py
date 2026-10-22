"""The task log lines past their retention (#305): the beat sends ``purge_task_logs`` once an hour, the
backend deletes what is older than its TASK_LOG_RETENTION_DAYS."""

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared


@celery_app.task(name="app.tasks.purge_task_logs")
def purge_task_logs() -> int:
    deleted = _shared.backend_client.purge_task_logs()
    if deleted:
        logger.info(f"Task logs: {deleted} line(s) past their retention purged")
    return deleted
