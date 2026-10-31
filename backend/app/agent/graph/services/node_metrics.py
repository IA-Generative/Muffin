"""The time of each step of the agent's graph, reported like a task's (app/execution_metrics.py) with
kind "node": a breakdown of the run's task, which holds the memory and is what the totals count.

A step runs in a thread of its own (the parallel research tasks included), so the CPU is that thread's."""

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.agent.execution_metrics import report
from app.agent.usage_context import set_usage


def measured(name: str, node: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """The node, reporting what one execution of it cost - whatever way it ends."""

    @functools.wraps(node)
    async def run(state: Any, *args: Any, **kwargs: Any) -> Any:
        # The run this step is for (a fanned-out step may run in a task that never saw it), so the backend can tell
        # whose consumption it is.
        if isinstance(state, dict) and state.get("run_id"):
            set_usage(run_id=state["run_id"])
        wall = time.monotonic()
        try:
            return await node(state, *args, **kwargs)
        finally:
            report("node", name, time.monotonic() - wall)

    return run
