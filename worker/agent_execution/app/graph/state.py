import operator
from typing import Annotated, Any, Literal, TypedDict

TaskStatus = Literal["pending", "ready", "blocked", "running", "completed", "failed"]


class ResearchTask(TypedDict):
    """One unit of research work in the DAG built by decompose_query/build_research_plan.
    Ids are stable for the lifetime of a run - replan_research adds new tasks rather than
    mutating a completed one, so past evidence always traces back to the task that found it."""

    id: str
    query: str
    intent: str | None
    dependencies: list[str]
    status: TaskStatus
    candidate_vdbs: list[str]
    selected_vdbs: list[str]
    search_queries: list[str]
    results: list[dict[str, Any]]
    error: str | None


class Evidence(TypedDict):
    id: str
    task_id: str
    vdb_id: str
    source_id: str
    content: str
    metadata: dict[str, Any]
    relevance_score: float | None
    retrieval_query: str


class CoverageResult(TypedDict):
    status: Literal["sufficient", "insufficient"]
    missing_information: list[str]
    reasoning: str | None


class GroundingResult(TypedDict):
    valid: bool
    unsupported_claims: list[str]


def _merge_by_id(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reducer for research_tasks: parallel research_task branches each return an update for
    their own task id, and replan_research appends brand-new ids - never a plain list overwrite
    that would drop the other branches' work (§16/§26 of the architecture brief)."""
    merged = {item["id"]: item for item in left}
    for item in right:
        merged[item["id"]] = item
    return list(merged.values())


class ResearchTaskInput(TypedDict):
    """Input schema for one `research_task` fan-out branch (§11) - deliberately narrower than
    AgentState: a task never sees the other tasks, only its own query and the accessible VDBs."""

    run_id: str
    user_id: str
    accessible_vdbs: list[dict[str, Any]]
    task: ResearchTask


class AgentState(TypedDict):
    # --- identity/context (§3, never inferred by the LLM) ---
    run_id: str
    user_id: str
    conversation_id: str

    original_query: str
    messages: list[dict[str, Any]]

    # --- permission barrier (§4) ---
    accessible_vdbs: list[dict[str, Any]]

    # --- understanding (§5/§6) ---
    query_analysis: dict[str, Any]

    # --- research DAG (§7-§10) ---
    research_plan: dict[str, Any]
    research_tasks: Annotated[list[ResearchTask], _merge_by_id]
    completed_task_ids: Annotated[list[str], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]

    # --- evidence (§15-§16) ---
    # `evidence` only ever grows via the operator.add reducer (each research_task branch appends
    # its own findings); merge_evidence can't dedupe it in place without double-applying the
    # reducer on its own output, so the deduped view downstream nodes read from lives separately.
    evidence: Annotated[list[Evidence], operator.add]
    deduped_evidence: list[Evidence]

    # --- coverage / replan loop (§17-§20) ---
    coverage_result: CoverageResult | None
    plan_version: int
    replan_count: int

    # --- answer (§21-§22) ---
    answer_context: dict[str, Any] | None
    answer: str | None
    citations: list[dict[str, Any]]

    # --- grounding loop (§23-§24) ---
    grounding_result: GroundingResult | None
    grounding_research_count: int

    # --- lifecycle (§30) ---
    execution_status: str
    cancelled: bool
