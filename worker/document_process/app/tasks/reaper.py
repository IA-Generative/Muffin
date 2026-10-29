"""The tasks stuck running past their timeout: the beat sends ``reap_stuck_tasks`` once an hour, the
backend marks them failed (see POST /internal/tasks/reap). A task whose worker died never reports
its end, and would otherwise read as "in progress" for ever."""

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared


@celery_app.task(name="app.tasks.reap_stuck_tasks")
def reap_stuck_tasks() -> int:
    reaped = _shared.backend_client.reap_stuck_tasks()
    if reaped:
        logger.info(f"Tasks: {reaped} stuck task(s) marked as failed")
    return reaped
