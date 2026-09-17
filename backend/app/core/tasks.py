from celery import Celery
from celery.result import AsyncResult

from app.config import RedisSettings

_redis_settings = RedisSettings()
_celery_app = Celery("muffin_backend_producer", broker=_redis_settings.REDIS_URL, backend=_redis_settings.REDIS_URL)
# Celery's own default (1 day) would make a task's status silently fall back
# to PENDING once its result key expires, well before anyone looking at a
# task history would expect it to disappear.
_celery_app.conf.result_expires = 60 * 60 * 24 * 7

# Must match worker/document_process/app/celery_app.py's queue and task name
# exactly - the backend only produces this task, it never imports the
# worker's code (separate service, separate deploy).
DOCUMENT_PROCESSING_QUEUE = "document_processing"
PROCESS_DOCUMENT_TASK = "app.tasks.process_document"

# Same reasoning, for the separate worker/agent_execution service - a
# distinct queue so scaling/deploying one worker never affects the other,
# even though both are produced from this same Celery app instance.
AGENT_EXECUTION_QUEUE = "agent_execution"
RUN_AGENT_TASK = "app.tasks.run_agent"
RESUME_AGENT_TASK = "app.tasks.resume_agent"


def enqueue_process_document(document_id: str) -> str:
    """Returns the Celery task id, so the caller can record it (see
    app/models/task.py) for later status lookups and revocation."""
    result = _celery_app.send_task(PROCESS_DOCUMENT_TASK, args=[document_id], queue=DOCUMENT_PROCESSING_QUEUE)
    return result.id


def enqueue_run_agent(run_id: str) -> str:
    """Returns the Celery task id, recorded on the Run row itself (see
    app/models/run.py) rather than a separate Task row - a run already has
    the id, and it's 1:1 with its own dispatch (no parent/children)."""
    result = _celery_app.send_task(RUN_AGENT_TASK, args=[run_id], queue=AGENT_EXECUTION_QUEUE)
    return result.id


def enqueue_resume_agent(run_id: str, answer: str) -> str:
    """Continues a run paused on request_clarification's interrupt() (§31) - a distinct task
    name/args from enqueue_run_agent rather than overloading it, since resuming re-enters the
    same checkpointed graph execution (Command(resume=...)) instead of starting a fresh one."""
    result = _celery_app.send_task(RESUME_AGENT_TASK, args=[run_id, answer], queue=AGENT_EXECUTION_QUEUE)
    return result.id


def get_task_status(celery_task_id: str) -> str:
    return AsyncResult(celery_task_id, app=_celery_app).status


def revoke_task(celery_task_id: str) -> None:
    _celery_app.control.revoke(celery_task_id, terminate=True)
