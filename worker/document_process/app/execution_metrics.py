"""What each task of this worker costs the machine, sent to the backend when it ends: how long it took, the
CPU time it used and the memory it held at most (shown in "Ma consommation" with an estimated energy).

- `task_prerun` starts measuring, `task_postrun` sends. The measure is the process's CPU time and memory
  when the task has the process to itself (prefork, solo); when other tasks ran in it meanwhile (a pool of
  threads), the process's figures would be theirs too: the CPU time is then the task's own thread's and the
  memory the process's divided by the most tasks that shared it.
- The memory is the highest a sampler thread saw while the task ran. The CPU time is the difference of the
  clocks, so a thread the task starts (the agent's parallel research) is counted.
- The sending never fails a task and never makes it wait: a thread sends what the tasks report, and what
  could not be sent is dropped.
"""

import os
import queue
import resource
import threading
import time
from contextvars import ContextVar
from typing import Any

from celery.signals import task_postrun, task_prerun
from loguru import logger

from app.backend_client import backend_client
from app.usage_context import current_usage

SAMPLE_SECONDS = 0.25
# Sent in the last second of a task: a task that ends the worker's life must not lose its numbers.
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


class _Measure:
    def __init__(self) -> None:
        self.wall = time.monotonic()
        self.process_cpu = time.process_time()
        self.thread_cpu = time.thread_time()
        self.peak_rss = _rss_bytes()
        self.shared_with = 1  # the most tasks running in this process at once while this one did


class _Sampler:
    """Watches the memory of the process while tasks run, and how many share it."""

    def __init__(self) -> None:
        self._reset()
        os.register_at_fork(after_in_child=self._reset)

    def _reset(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, _Measure] = {}
        self._thread: threading.Thread | None = None

    def start(self, task_id: str, measure: _Measure) -> None:
        with self._lock:
            self._active[task_id] = measure
            for other in self._active.values():
                other.shared_with = max(other.shared_with, len(self._active))
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="execution-sampler", daemon=True)
                self._thread.start()

    def stop(self, task_id: str) -> _Measure | None:
        with self._lock:
            measure = self._active.pop(task_id, None)
        if measure is not None:
            measure.peak_rss = max(measure.peak_rss, _rss_bytes())
        return measure

    def _run(self) -> None:
        while True:
            time.sleep(SAMPLE_SECONDS)
            with self._lock:
                if not self._active:
                    self._thread = None
                    return
                rss = _rss_bytes()
                for measure in self._active.values():
                    measure.peak_rss = max(measure.peak_rss, rss)


class _Sender:
    """The metrics waiting to be sent, and the thread sending them - started in the process that reports,
    with prefork a thread doesn't survive the fork of a pool's child."""

    def __init__(self) -> None:
        self._reset()
        os.register_at_fork(after_in_child=self._reset)

    def _reset(self) -> None:
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


_sampler = _Sampler()
_sender = _Sender()
# Started by task_prerun, in the thread the task runs in.
_current: ContextVar[tuple[str, _Measure] | None] = ContextVar("execution_measure", default=None)


def report(kind: str, step: str, duration_seconds: float, cpu_seconds: float, peak_rss_bytes: int | None) -> None:
    """Queues one metric, attributed to whatever the current task's LLM calls are (usage_context)."""
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


@task_prerun.connect
def _start_task(task_id: str | None = None, **_: Any) -> None:
    if task_id is None:
        return
    measure = _Measure()
    _sampler.start(task_id, measure)
    _current.set((task_id, measure))


@task_postrun.connect
def _end_task(task: Any = None, **_: Any) -> None:
    started = _current.get()
    if started is None:
        return
    _current.set(None)
    task_id, measure = started
    if _sampler.stop(task_id) is None:
        return
    shared = measure.shared_with > 1
    cpu = (time.thread_time() - measure.thread_cpu) if shared else (time.process_time() - measure.process_cpu)
    try:
        report(
            "task",
            task.name.rsplit(".", 1)[-1],
            time.monotonic() - measure.wall,
            cpu,
            measure.peak_rss // measure.shared_with,
        )
        _sender.flush()
    except Exception:
        logger.exception("Could not report an execution metric")
