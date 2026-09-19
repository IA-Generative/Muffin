import operator
from typing import Annotated, Any, Literal, TypedDict

TaskStatus = Literal["pending", "ready", "blocked", "running", "completed", "failed"]

# What research_task actually does for this task, decided by decompose_query (§ meta-query
# tools): "search" is the default (evidence search over chunks); the others answer questions
# about the knowledge bases themselves rather than their content, using data the backend
# already scoped to this user - never a fresh, unchecked lookup by an LLM-supplied id.
TaskTool = Literal["search", "list_collections", "collection_summary", "list_documents", "page_content", "web_search"]


class ResearchTask(TypedDict):
    """One unit of research work in the DAG built by decompose_query/build_research_plan.
    Ids are stable for the lifetime of a run - replan_research adds new tasks rather than
    mutating a completed one, so past evidence always traces back to the task that found it."""

    id: str
    query: str
    intent: str | None
    tool: TaskTool
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
    chat_model: str | None
    pinned_vdb_ids: list[str]
    web_search_enabled: bool


class AgentState(TypedDict):
    # --- identity/context (§3, never inferred by the LLM) ---
    run_id: str
    user_id: str
    # Snapshot of the user's Keycloak groups at run creation time (Run.user_groups) - only
    # consumed by load_accessible_vdbs, to include collections shared to one of these groups.
    user_groups: list[str]
    conversation_id: str

    original_query: str
    # The user's literal message, rewritten by analyze_query to stand on its own when it refers
    # back to the conversation (e.g. "elle" -> "the AgentControl collection") - what every node
    # doing actual research work searches/reasons over instead of original_query, so a follow-up
    # question in the same conversation isn't treated as a cold, context-free string.
    contextualized_query: str
    messages: list[dict[str, Any]]

    # Resolved once by AgentService.run() and threaded through every node from here on, instead
    # of each of them separately calling GET /api/internal/llm/default-chat-model - the model
    # doesn't change mid-run, so doing that per node was a pure latency tax (one extra
    # worker<->backend round trip before every single LLM call, on the critical path).
    chat_model: str | None

    # Collections the user explicitly attached to this message (the chat composer's "+"
    # picker) - always searched regardless of what VDB routing's own relevance guess would have
    # picked, see select_relevant_vdbs. Empty list, never None, when nothing was attached.
    pinned_vdb_ids: list[str]

    # Opt-in per message (chat composer toggle, off by default) - see Run.web_search_enabled.
    # Read by decompose_query (only offers the "web_search" tool to the planner when true) and
    # research_task (refuses to run it otherwise, an independent second gate).
    web_search_enabled: bool

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
