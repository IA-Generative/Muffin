from typing import Any

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.planning import compute_ready_and_blocked
from app.graph.state import AgentState


def build_research_plan(state: AgentState) -> dict[str, Any]:
    """Turns the DAG produced by decompose_query into an execution plan: which tasks are ready
    to run now vs blocked on a dependency (§8). Persisted to the Run row so a worker restart or
    a HITL pause can resume without re-deriving it (§32)."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "build_research_plan", "Planning the research")
    tasks = state["research_tasks"]
    ready, blocked = compute_ready_and_blocked(tasks, completed_ids=set(), running_or_done_ids=set())
    ready_tasks = [{**task, "status": "ready"} for task in ready]

    plan = {
        "plan_version": state.get("plan_version", 0),
        "ready": [t["id"] for t in ready_tasks],
        "blocked": [t["id"] for t in blocked],
        "max_parallel_tasks": settings.MAX_PARALLEL_TASKS,
    }
    backend_client.update_run_state(run_id, research_plan=plan, plan_version=state.get("plan_version", 0))
    emit(run_id, "research_plan_created", plan)
    return {"research_plan": plan, "research_tasks": ready_tasks}
