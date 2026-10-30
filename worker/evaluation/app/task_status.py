"""Reports each task's lifecycle to the backend, so its status is persisted in Postgres instead of
being inferred from Celery's result backend - which cannot tell an id it no longer knows from one
still waiting in the queue.

- `task_prerun` -> STARTED
- `task_postrun` -> SUCCESS, FAILURE (with the exception), REVOKED (an Ignore, which is how a
  revoked task stops), or STARTED again for a RETRY.

Best-effort: a task never fails because the backend could not be told, and a task with no Task row
(the beat's, the agent's runs) is a no-op on the backend side.
"""

from typing import Any

from celery.signals import task_postrun, task_prerun
from loguru import logger

from app.backend_client import backend_client

# Celery's state after the task ran -> the status the backend persists. IGNORED is how a task
# revoked before it started stops (see app/task_revocation.py); REJECTED means it was requeued.
_STATES = {
    "SUCCESS": "SUCCESS",
    "FAILURE": "FAILURE",
    "IGNORED": "REVOKED",
    "RETRY": "STARTED",
}


def _report(task_id: str | None, status: str, error: str | None = None) -> None:
    if task_id is None:
        return
    try:
        backend_client.update_task_status(task_id, status, error)
    except Exception as exc:
        logger.debug(f"Could not report task {task_id} as {status}: {exc}")


@task_prerun.connect
def _started(task_id: str | None = None, **_: Any) -> None:
    _report(task_id, "STARTED")


@task_postrun.connect
def _finished(task_id: str | None = None, state: str | None = None, retval: Any = None, **_: Any) -> None:
    status = _STATES.get(state or "")
    if status is None:
        return
    _report(task_id, status, _error_of(retval) if status == "FAILURE" else None)


def _error_of(retval: Any) -> str | None:
    return str(retval) if isinstance(retval, BaseException) else None
