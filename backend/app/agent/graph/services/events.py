from typing import Any

from app.agent.backend_client import backend_client
from app.agent.usage_context import set_usage


def emit(run_id: str, event_type: str, data: dict[str, Any] | None = None, task_id: str | None = None) -> None:
    backend_client.add_run_event(run_id, event_type, data, task_id)


def set_activity(run_id: str, node: str, activity: str) -> None:
    """Keeps Run.current_node/current_activity fresh for a client polling GET /api/runs/{id} -
    run_events (emit above) are the durable log, but a poller only ever sees this pair of fields
    change, so every node calls this once at the top, not just the terminal statuses.

    Also names the node as the step of the LLM calls that follow (see app/usage_context.py) -
    with the run id again, since a fanned-out node may run in a thread of its own."""
    set_usage(run_id=run_id, step=node)
    backend_client.update_run_status(run_id, "running", node, activity)


def is_cancelled(run_id: str) -> bool:
    """Cooperative cancellation check (§30) - called at the start of every node instead of
    trusting Celery's revoke alone, which can't interrupt a node already mid-flight."""
    return bool(backend_client.get_run(run_id)["cancel_requested"])
