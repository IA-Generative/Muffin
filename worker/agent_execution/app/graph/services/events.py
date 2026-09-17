from typing import Any

from app.backend_client import backend_client


def emit(run_id: str, event_type: str, data: dict[str, Any] | None = None, task_id: str | None = None) -> None:
    backend_client.add_run_event(run_id, event_type, data, task_id)


def is_cancelled(run_id: str) -> bool:
    """Cooperative cancellation check (§30) - called at the start of every node instead of
    trusting Celery's revoke alone, which can't interrupt a node already mid-flight."""
    return bool(backend_client.get_run(run_id)["cancel_requested"])
