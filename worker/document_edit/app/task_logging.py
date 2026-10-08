import io
from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger

from app.backend_client import backend_client


@contextmanager
def capture_task_logs(celery_task_id: str) -> Iterator[None]:
    """Captures every loguru line emitted while a task runs (not just on
    failure - the user wants the raw output available in all cases) and
    reports it back to the backend against this task's Task row, win or
    lose. Reporting happens even on exception, then the exception is
    re-raised so Celery still marks the task FAILURE."""
    buffer = io.StringIO()
    sink_id = logger.add(buffer, level="DEBUG", enqueue=False)
    try:
        yield
    finally:
        logger.remove(sink_id)
        try:
            backend_client.set_task_logs(celery_task_id, buffer.getvalue())
        except Exception:
            logger.exception(f"Failed to report logs for task {celery_task_id} back to the backend")
