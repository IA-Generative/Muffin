"""What the steps of a run cost, recorded when each ends: how long it took, and the memory the process held (shown in
"Ma consommation" with an estimated energy).

The agent runs on the backend's event loop, which many runs and requests share: the CPU time of a step cannot be told
from the others' any more, so only its wall time is reported (the CPU is 0 - what a run spends waiting for a model or a
search is not CPU). Recording never fails a run and never makes it wait: each metric is sent by a task of its own, and
what could not be sent is dropped."""

import asyncio
import contextlib
import os
import resource
import time
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from app.agent.backend_client import backend_client
from app.agent.usage_context import current_usage

# Metrics being sent at once, at most: a backend that does not answer must not pile tasks up.
MAX_IN_FLIGHT = 200
_PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")
_pending: set[asyncio.Task] = set()


def _rss_bytes() -> int:
    """The memory the process holds right now (Linux), its highest so far where /proc isn't there."""
    try:
        with open("/proc/self/statm") as statm:
            return int(statm.read().split()[1]) * _PAGE_BYTES
    except (OSError, ValueError, IndexError):
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


async def _send(metric: dict[str, Any]) -> None:
    try:
        await backend_client.add_execution_metric(metric)
    except Exception as error:
        logger.warning(f"Could not send an execution metric: {error}")


def report(kind: str, step: str, duration_seconds: float, peak_rss_bytes: int | None = None) -> None:
    """Sends one metric in the background, attributed to whatever the current run's LLM calls are (usage_context)."""
    if len(_pending) >= MAX_IN_FLIGHT:
        logger.warning("Too many execution metrics waiting to be sent, one dropped")
        return
    usage = current_usage() or {}
    metric = {
        "kind": kind,
        "step": step,
        "duration_seconds": max(duration_seconds, 0.0),
        "cpu_seconds": 0.0,
        "peak_rss_bytes": peak_rss_bytes,
        **{key: usage[key] for key in ("user_id", "run_id", "document_id", "collection_id") if key in usage},
    }
    try:
        task = asyncio.get_running_loop().create_task(_send(metric))
    except RuntimeError:  # no loop: nothing to send it on
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def flush(timeout: float = 5.0) -> None:
    """Waits, up to `timeout`, for what was reported to be sent."""
    if _pending:
        await asyncio.wait(set(_pending), timeout=timeout)


@contextlib.asynccontextmanager
async def measured_run(step: str = "run_agent") -> AsyncIterator[None]:
    """The run as a whole, reported like a task: its time and the process's memory at its end."""
    wall = time.monotonic()
    try:
        yield
    finally:
        report("task", step, time.monotonic() - wall, _rss_bytes())
        await flush()
