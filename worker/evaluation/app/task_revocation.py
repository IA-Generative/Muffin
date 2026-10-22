"""A task the user revoked stays revoked, and stops wherever it runs.

Celery's own revoke is a broadcast to the workers up at that moment, kept in their memory, and a kill
that only a prefork pool can carry out:
- a task revoked while it waits in the queue runs all the same on a pod that starts afterwards (a
  deploy, KEDA scaling up), and one whose worker died runs again when Redis hands it out again, after
  the visibility timeout - hours;
- a pool of threads (the enrichment pod) cannot kill a task: it went on running, "revoked".

The backend therefore also leaves a flag in Redis for each revoked task (backend/app/core/tasks.py,
`revoke_tasks` - the key must be the same). Here:
- `RevocableTask` looks at it when a task starts, and drops the task if it is there;
- `raise_if_revoked` is called where a task spends its time (an LLM call, an embedding batch): a task that
  runs in a thread stops at the next one.
"""

from contextvars import ContextVar
from typing import Any

from celery import Task
from celery.exceptions import Ignore
from loguru import logger

REVOKED_KEY = "muffin:revoked:{task_id}"

# The task being run and the app it belongs to - per thread, copied into the threads it starts
# (contextvars.copy_context), like task_logging's.
_running: ContextVar[tuple[Any, str] | None] = ContextVar("revocable_task", default=None)


class TaskRevoked(Ignore):
    """Raised in a task that was revoked while it ran. An Ignore, so that Celery drops the task quietly:
    its state is REVOKED already, the backend stored it."""


def _is_revoked(app: Any, task_id: str) -> bool:
    try:
        return bool(app.backend.client.exists(REVOKED_KEY.format(task_id=task_id)))
    except Exception as error:
        # Redis not answering never stops a task that was started: it is looked at again at the next call.
        logger.debug(f"Could not look whether task {task_id} was revoked: {error}")
        return False


class RevocableTask(Task):
    def before_start(self, task_id: str, args: tuple, kwargs: dict) -> None:
        _running.set((self.app, task_id))
        if _is_revoked(self.app, task_id):
            logger.info(f"Task {self.name}[{task_id}] was revoked: not run")
            # track_started has written STARTED just before this one: REVOKED again.
            self.app.backend.mark_as_revoked(task_id, reason="revoked by the user")
            raise TaskRevoked()


def raise_if_revoked() -> None:
    """For the tasks that run in a pool of threads, which Celery cannot kill: called between two slow
    steps. Does nothing outside a task."""
    running = _running.get()
    if running is not None and _is_revoked(*running):
        logger.info(f"Task {running[1]} was revoked: stopped")
        raise TaskRevoked()
