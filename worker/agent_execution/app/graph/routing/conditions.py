from langgraph.types import Send

from app.config import settings
from app.graph.nodes.gate import fan_out
from app.graph.state import AgentState


def route_or_cancel(next_node: str):
    """Every plain edge of the graph goes through this instead of an `add_edge`, so a cancellation request is honored
    between any two nodes (§30). The node that saw the request set `cancelled`: no call to the backend is made here."""

    def _route(state: AgentState) -> str:
        return "cancelled" if state.get("cancelled") else next_node

    return _route


def _ready_tasks(state: AgentState, prefix: str | None = None) -> list:
    """The tasks of the plan not yet run (the plan's tasks are independent, so all of them are ready at once), within
    the parallelism and total-task budgets (§28)."""
    done = set(state["completed_task_ids"]) | set(state["failed_task_ids"])
    ready = [
        t
        for t in state["research_tasks"]
        if t["id"] not in done and (t["id"].startswith(prefix) if prefix else not t["id"].startswith("wide-"))
    ]
    budget_left = max(settings.MAX_TOTAL_TASKS - len(done), 0)
    return ready[: min(settings.MAX_PARALLEL_TASKS, budget_left)]


def after_plan(state: AgentState) -> str | list[Send]:
    """Where the plan sends the run. Answering now and asking end it: the plan already wrote the answer."""
    if state.get("cancelled"):
        return "cancelled"
    mode = state["plan"]["mode"]
    if mode in ("direct", "clarify"):
        return "end"
    if mode == "help":
        return "answer_help"
    if mode in ("edit", "create"):
        return mode
    batch = _ready_tasks(state)
    return fan_out(state, batch) if batch else "gate"


def after_gate(state: AgentState) -> str:
    """Not enough found: widen the search to every collection once, if the plan had narrowed it. Otherwise write the
    answer - which says plainly what could not be established."""
    if state.get("cancelled"):
        return "cancelled"
    insufficient = state["coverage_result"]["status"] == "insufficient"
    return "widen_search" if insufficient and state["scope_ids"] and not state["widened"] else "build_answer_context"


def after_widen_search(state: AgentState) -> str | list[Send]:
    batch = _ready_tasks(state, prefix="wide-")
    return fan_out(state, batch) if batch else "build_answer_context"
