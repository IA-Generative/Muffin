"""Logging of this worker (#305): loguru for everything, and each task's lines sent to the backend while
it runs - a task's logs (GET /api/tasks/{id}/logs) and a document's (all the tasks of its pipeline) can
be followed live in Muffin, and are kept even when the pod dies halfway through a task.

- What goes through the standard `logging` (Celery, the beat, docling, boto...) is handed to loguru,
  and Celery leaves the logging alone (`setup_logging`).
- `task_prerun` puts the task being run in a context variable - per thread, so a pool of threads keeps
  each task's lines apart - and a patcher adds it to every line logged meanwhile: celery_task_id,
  task_name, and the document_id/collection_id its arguments carry. stdout shows it too (LOG_FORMAT=json).
- The lines of a task at TASK_LOG_LEVEL or above are buffered and sent in batches every
  FLUSH_SECONDS by a thread, and at the end of the task. The backend being down never fails a task:
  the lines wait for the next batch, up to MAX_BUFFERED, the newer ones dropped past that.
"""

import inspect
import logging
import os
import sys
import threading
import traceback
import uuid
from contextvars import ContextVar
from typing import Any

import httpx
from celery.signals import setup_logging, task_postrun, task_prerun
from loguru import logger

from app.backend_client import backend_client
from app.config import settings

FLUSH_SECONDS = 2.0
BATCH_SIZE = 500
MAX_BUFFERED = 5000
# A line longer than this (a huge payload logged by mistake) is cut: the batch must stay small.
MAX_MESSAGE_CHARS = 20_000
# The ids a task's arguments may carry that the backend files its lines under.
_IDS = ("document_id", "collection_id")

_task: ContextVar[dict[str, str] | None] = ContextVar("task_log_context", default=None)


class InterceptHandler(logging.Handler):
    """Hands a standard `logging` record to loguru - loguru's own recipe."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Back to the frame that called `logging`, so the line says where it was logged from.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class _Shipper:
    """The lines waiting to be sent, and the thread sending them. Started in the process that logs:
    with prefork, a thread doesn't survive the fork of a pool's child."""

    def __init__(self) -> None:
        self._reset()
        os.register_at_fork(after_in_child=self._reset)

    def _reset(self) -> None:
        self._lock = threading.Lock()
        # One send at a time, so that a task's lines arrive in the order they were logged.
        self._send_lock = threading.Lock()
        self._lines: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None

    def put(self, line: dict[str, Any]) -> None:
        with self._lock:
            # Past MAX_BUFFERED (the backend down for a while), the new lines are dropped: stdout has them.
            if len(self._lines) < MAX_BUFFERED:
                self._lines.append(line)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="task-log-shipper", daemon=True)
                self._thread.start()

    def flush(self) -> None:
        with self._send_lock:
            while True:
                with self._lock:
                    batch = self._lines[:BATCH_SIZE]
                if not batch:
                    return
                try:
                    backend_client.add_task_logs(batch)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code >= 500:
                        return  # sent again with the next batch
                    # Refused as it is: sending it again would be refused all the same.
                    logger.warning(f"{len(batch)} task log line(s) refused by the backend: {error}")
                except Exception as error:
                    logger.warning(f"Could not send {len(batch)} task log line(s), will try again: {error}")
                    return
                with self._lock:
                    # Only what was sent: lines logged meanwhile were appended after it.
                    del self._lines[: len(batch)]

    def _run(self) -> None:
        stop = threading.Event()
        while not stop.wait(FLUSH_SECONDS):
            self.flush()


_shipper = _Shipper()


def _add_task(record: Any) -> None:
    task = _task.get()
    if task is not None:
        record["extra"].update(task)


def _ship(message: Any) -> None:
    record = message.record
    text = record["message"]
    if record["exception"] is not None:
        error_type, error, error_traceback = record["exception"]
        text = f"{text}\n{''.join(traceback.format_exception(error_type, error, error_traceback))}".rstrip()
    extra = record["extra"]
    _shipper.put(
        {
            "celery_task_id": extra["celery_task_id"],
            "task_name": extra["task_name"],
            "document_id": extra.get("document_id"),
            "collection_id": extra.get("collection_id"),
            "ts": record["time"].isoformat(),
            "level": record["level"].name,
            "message": text[:MAX_MESSAGE_CHARS],
            "extra": {"module": record["name"], "function": record["function"], "line": record["line"]},
        }
    )


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _console_format(record: Any) -> str:
    """loguru's default, plus the task a line was logged by - kubectl logs tells them apart too."""
    extra = record["extra"]
    task = f" | <magenta>{extra['task_name']}[{extra['celery_task_id']}]</magenta>" if "celery_task_id" in extra else ""
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level>"
        + task
        + " | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>\n{exception}"
    )


def configure() -> None:
    logger.remove()
    logger.configure(patcher=_add_task)
    if settings.LOG_FORMAT == "json":
        logger.add(sys.stdout, level=settings.LOG_LEVEL, serialize=True)
    else:
        logger.add(sys.stdout, level=settings.LOG_LEVEL, format=_console_format, colorize=True)
    logger.add(_ship, level=settings.TASK_LOG_LEVEL, filter=lambda record: "celery_task_id" in record["extra"])
    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=logging.getLevelNamesMapping().get(settings.LOG_LEVEL.upper(), logging.INFO),
        force=True,
    )
    # One line per backend call: the task's own lines say what it does.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@setup_logging.connect
def _leave_logging_alone(**_: Any) -> None:
    """Connected, Celery doesn't set the logging up itself: configure() did."""


@task_prerun.connect
def _start_task(
    task_id: str | None = None, task: Any = None, args: tuple | None = None, kwargs: dict | None = None, **_: Any
) -> None:
    """Every task is identified by its id and name, plus whichever ids its arguments carry - directly
    (document_id=...) or in a payload dict (document_edit's tasks)."""
    try:
        arguments = inspect.signature(task.run).bind_partial(*(args or ()), **(kwargs or {})).arguments
    except (TypeError, ValueError):
        arguments = {}
    payload = arguments.get("payload") if isinstance(arguments.get("payload"), dict) else {}
    context = {"celery_task_id": task_id, "task_name": task.name}
    for key in _IDS:
        value = arguments.get(key) or payload.get(key)
        if value and _is_uuid(value):
            context[key] = str(value)
    _task.set(context)


@task_postrun.connect
def _end_task(**_: Any) -> None:
    """The task's last lines are sent now, not a couple of seconds later - Celery's own line about how
    it ended included."""
    _task.set(None)
    _shipper.flush()


configure()
