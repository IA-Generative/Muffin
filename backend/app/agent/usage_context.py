"""What the LLM calls of the task being run are for - sent along with each of them so the backend
can record whose consumption they are (backend/app/services/usage_service.py)."""

from contextvars import ContextVar
from typing import Any

_usage: ContextVar[dict[str, Any] | None] = ContextVar("llm_usage", default=None)


def current_usage() -> dict[str, Any] | None:
    return _usage.get()


def set_usage(**fields: Any) -> None:
    """Narrows the context for the calls that follow, e.g. the agent graph node now running."""
    _usage.set({**(_usage.get() or {}), **{key: str(value) for key, value in fields.items() if value}})


def start_run(run_id: str, user_id: str | None = None) -> None:
    """The context of a run: its step is the run's own until a node narrows it, see set_usage."""
    _usage.set({"step": "run_agent", "run_id": run_id, **({"user_id": user_id} if user_id else {})})
