"""What the LLM calls of the task being run are for - sent along with each of them so the backend
can record whose consumption they are (backend/app/services/usage_service.py)."""

import inspect
from contextvars import ContextVar
from typing import Any

from celery.signals import task_prerun

# The ids the backend can attribute a call from, most specific first.
_IDS = ("user_id", "run_id", "document_id", "collection_id")

_usage: ContextVar[dict[str, Any] | None] = ContextVar("llm_usage", default=None)


def current_usage() -> dict[str, Any] | None:
    return _usage.get()


def set_usage(**fields: Any) -> None:
    """Narrows the context for the calls that follow, e.g. the agent graph node now running."""
    _usage.set({**(_usage.get() or {}), **{key: str(value) for key, value in fields.items() if value}})


@task_prerun.connect
def _start_task(task: Any = None, args: tuple | None = None, kwargs: dict | None = None, **_: Any) -> None:
    """Every task starts from its own name as the step and whichever ids its arguments carry -
    directly (document_id=...) or in a payload dict (document_edit's tasks)."""
    try:
        arguments = inspect.signature(task.run).bind_partial(*(args or ()), **(kwargs or {})).arguments
    except (TypeError, ValueError):
        arguments = {}
    payload = arguments.get("payload") if isinstance(arguments.get("payload"), dict) else {}
    context = {"step": task.name.rsplit(".", 1)[-1]}
    for key in _IDS:
        value = arguments.get(key) or payload.get(key)
        if value:
            context[key] = str(value)
    _usage.set(context)
