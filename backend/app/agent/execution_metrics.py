"""What the steps of a run cost the machine, recorded when each ends: how long it took, the CPU time it used and
the memory
the process held (shown in "Ma consommation" with an estimated energy).

The agent runs in a thread of the backend, so the CPU time is the thread's own and the memory the process's.
Recording never
fails a run and never makes it wait: a thread sends what the steps report (see graph/services/node_metrics.py) and
what could
not be sent is dropped."""

import contextlib
import os
import queue
import resource
import threading
import time
from collections.abc import Iterator
from typing import Any

from loguru import logger

from app.agent.backend_client import backend_client
from app.agent.usage_context import current_usage

FLUSH_TIMEOUT_SECONDS = 5.0
MAX_QUEUED = 1000
_PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")


def _rss_bytes() -> int:
    """The memory the process holds right now (Linux), its highest so far where /proc isn't there."""
    try:
        with open("/proc/self/statm") as statm:
            return int(statm.read().split()[1]) * _PAGE_BYTES
    except (OSError, ValueError, IndexError):
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


class _Sender:
    """The metrics waiting to be sent, and the thread sending them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(MAX_QUEUED)
        self._thread: threading.Thread | None = None

    def put(self, metric: dict[str, Any]) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="execution-sender", daemon=True)
                self._thread.start()
        try:
            self._queue.put_nowait(metric)
        except queue.Full:
            logger.warning("Too many execution metrics waiting to be sent, one dropped")

    def flush(self) -> None:
        """Waits, up to FLUSH_TIMEOUT_SECONDS, for what was reported to be sent."""
        deadline = time.monotonic() + FLUSH_TIMEOUT_SECONDS
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)

    def _run(self) -> None:
        while True:
            metric = self._queue.get()
            try:
                backend_client.add_execution_metric(metric)
            except Exception as error:
                logger.warning(f"Could not send an execution metric: {error}")
            finally:
                self._queue.task_done()


_sender = _Sender()


def report(kind: str, step: str, duration_seconds: float, cpu_seconds: float, peak_rss_bytes: int | None) -> None:
    """Queues one metric, attributed to whatever the current run's LLM calls are (usage_context)."""
    usage = current_usage() or {}
    _sender.put(
        {
            "kind": kind,
            "step": step,
            "duration_seconds": max(duration_seconds, 0.0),
            "cpu_seconds": max(cpu_seconds, 0.0),
            "peak_rss_bytes": peak_rss_bytes,
            **{key: usage[key] for key in ("user_id", "run_id", "document_id", "collection_id") if key in usage},
        }
    )


@contextlib.contextmanager
def measured_run(step: str = "run_agent") -> Iterator[None]:
    """The run as a whole, reported like a task: its time, its thread's CPU and the process's memory at its end."""
    wall, cpu = time.monotonic(), time.thread_time()
    try:
        yield
    finally:
        report("task", step, time.monotonic() - wall, time.thread_time() - cpu, _rss_bytes())
        _sender.flush()
