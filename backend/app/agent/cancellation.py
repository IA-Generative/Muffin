"""A run the user cancelled stops wherever it is, even in the middle of a wait.

Cancelling sets `cancel_requested` on the run, which every node looks at when it starts (the way that works whichever
backend pod receives the request). The pod that runs the agent is also told directly, so that what waits for something
slow - the SQL worker's answer - stops at its next look instead of at the next node."""

import threading

from app.agent.usage_context import current_usage

_cancelled: set[str] = set()
_lock = threading.Lock()


class RunCancelled(Exception):
    """Raised in a run that was cancelled while it waited."""


def mark_cancelled(run_id: str) -> None:
    with _lock:
        _cancelled.add(run_id)


def forget(run_id: str) -> None:
    with _lock:
        _cancelled.discard(run_id)


def raise_if_cancelled() -> None:
    """Called where a run spends its time (a wait for the SQL worker, a call to the model)."""
    run_id = (current_usage() or {}).get("run_id")
    with _lock:
        if run_id and run_id in _cancelled:
            raise RunCancelled(run_id)
