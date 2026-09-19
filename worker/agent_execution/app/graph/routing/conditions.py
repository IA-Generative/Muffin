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
                "chat_model": state["chat_model"],
                "pinned_vdb_ids": state["pinned_vdb_ids"],
                "web_search_enabled": state["web_search_enabled"],
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


def after_generate_answer(state: AgentState) -> str:
    """Skips the grounding check entirely for answers unlikely to need it (§ optimize latency) -
    it's a full extra LLM call re-reading the whole answer against the evidence, worth paying
    for a synthesized/multi-source answer but not for a deterministic knowledge-base lookup
    (counts, summaries - nothing to hallucinate a *claim* about) or a simple single-fact answer."""
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"

    completed_ids = set(state["completed_task_ids"])
    completed_tasks = [t for t in state["research_tasks"] if t["id"] in completed_ids]
    is_meta_only = bool(completed_tasks) and all(t.get("tool", "search") != "search" for t in completed_tasks)

    analysis = state["query_analysis"]
    is_simple_lookup = (
        analysis.get("intent") not in ("comparison", "synthesis")
        and not analysis.get("requires_multiple_sources")
        and analysis.get("complexity") == "simple"
    )

    return "end" if is_meta_only or is_simple_lookup else "validate_grounding"


def after_validate_grounding(state: AgentState) -> str:
    if state.get("cancelled") or is_cancelled(state["run_id"]):
        return "cancelled"
    grounding = state["grounding_result"]
    if grounding["valid"]:
        return "end"
    if state["grounding_research_count"] >= settings.MAX_GROUNDING_RESEARCHES:
        return "end"
    return "targeted_research"
