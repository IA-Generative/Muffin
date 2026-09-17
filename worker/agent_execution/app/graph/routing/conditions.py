from langgraph.types import Send

from app.config import settings
from app.graph.services.events import is_cancelled
from app.graph.services.planning import compute_ready_and_blocked
from app.graph.state import AgentState


def route_or_cancel(next_node: str):
    """Every edge in the graph goes through this instead of a plain add_edge, so a
    cancellation request is honored between any two nodes, not just at fixed checkpoints (§30)."""

    def _route(state: AgentState) -> str:
        return "cancelled" if state.get("cancelled") else next_node

    return _route


def after_analyze_query(state: AgentState) -> str:
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"
    if state["query_analysis"].get("ambiguous"):
        return "request_clarification"
    return "decompose_query"


def _ready_batch(state: AgentState) -> list:
    """Tasks currently runnable, capped by the parallelism and total-task budgets (§27/§28) - a
    dependency is never started before every task it depends on is in completed_task_ids."""
    tasks = state["research_tasks"]
    completed = set(state["completed_task_ids"])
    running_or_done = completed | set(state["failed_task_ids"])
    ready, _blocked = compute_ready_and_blocked(tasks, completed, running_or_done)
    if not ready:
        return []

    total_started = len(completed) + len(state["failed_task_ids"])
    budget_left = max(settings.MAX_TOTAL_TASKS - total_started, 0)
    return ready[: min(settings.MAX_PARALLEL_TASKS, budget_left)] if budget_left else []


def _fan_out(state: AgentState, batch: list) -> list[Send]:
    return [
        Send(
            "research_task",
            {
                "run_id": state["run_id"],
                "user_id": state["user_id"],
                "accessible_vdbs": state["accessible_vdbs"],
                "task": task,
            },
        )
        for task in batch
    ]


def execute_research_plan(state: AgentState):
    """Dynamic fan-out (§9/§10) from build_research_plan/replan_research - one Send per task
    currently ready. The number of branches is never hardcoded, it falls out of however many
    tasks decompose_query/replan_research produced."""
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"

    batch = _ready_batch(state)
    return _fan_out(state, batch) if batch else "merge_evidence"


def continue_dag_or_evaluate(state: AgentState):
    """Re-entered after every merge_evidence (§9/§27): a task blocked on a dependency that just
    completed becomes ready here and is fanned out again, *before* evaluate_coverage ever runs -
    the DAG must fully drain on its own, not rely on the coverage/replan loop to progress it."""
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"

    batch = _ready_batch(state)
    return _fan_out(state, batch) if batch else "evaluate_coverage"


def after_evaluate_coverage(state: AgentState) -> str:
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"
    coverage = state["coverage_result"]
    if coverage["status"] == "sufficient":
        return "build_answer_context"
    if state["replan_count"] >= settings.MAX_REPLANS:
        # Budget exhausted (§20): proceed with what we have rather than loop forever - the
        # final answer must say plainly that some information couldn't be established.
        return "build_answer_context"
    return "replan_research"


def after_validate_grounding(state: AgentState) -> str:
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"
    grounding = state["grounding_result"]
    if grounding["valid"]:
        return "end"
    if state["grounding_research_count"] >= settings.MAX_GROUNDING_RESEARCHES:
        return "end"
    return "targeted_research"
