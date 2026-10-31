import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

TaskStatus = Literal["pending", "ready", "blocked", "running", "completed", "failed"]

# What research_task actually does for this task, decided by decompose_query (§ meta-query
# tools): "search" is the default (evidence search over chunks); the others answer questions
# about the knowledge bases themselves rather than their content, using data the backend
# already scoped to this user - never a fresh, unchecked lookup by an LLM-supplied id.
TaskTool = Literal[
    "search",
    "list_collections",
    "collection_summary",
    "list_documents",
    "page_content",
    "tabular_query",
    "web_search",
    "time",
]


class ResearchTask(TypedDict):
    """One unit of research work, one per query of the plan.
    Ids are stable for the lifetime of a run - replan_research adds new tasks rather than
    mutating a completed one, so past evidence always traces back to the task that found it.
    """

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
    # Claims that cite an excerpt which does not support them (#402): {claim, cited, supported_by}.
    miscited_claims: NotRequired[list[dict[str, Any]]]
    # Claims the excerpts support, that cite none.
    uncited_claims: NotRequired[list[str]]
    # Cited excerpts of which the answer's passage is not in the excerpt (found without the model).
    unverified_citations: NotRequired[list[str]]


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
    AgentState: a task never sees the other tasks, only its own query and the collections to search.
    """

    run_id: str
    user_id: str
    accessible_vdbs: list[dict[str, Any]]
    # The collections this task searches (each with its sub-collections): chosen by the plan, widened by widen_search.
    scope_ids: list[str]
    task: ResearchTask
    chat_model: str | None
    web_search_enabled: bool


class AgentState(TypedDict):
    # --- identity/context (§3, never inferred by the LLM) ---
    run_id: str
    user_id: str
    # Snapshot of the user's Keycloak groups at run creation time (Run.user_groups) - only
    # consumed by prepare, to include collections shared to one of these groups.
    user_groups: list[str]
    conversation_id: str

    original_query: str
    # The user's message rewritten by the plan to stand on its own when it refers back to the conversation
    # ("elle" -> "the AgentControl collection"): what the research searches and the answer is written for.
    contextualized_query: str
    messages: list[dict[str, Any]]

    # Resolved once by AgentService.run() and threaded through every node from here on.
    chat_model: str | None

    # Collections the user explicitly attached to this message (the chat composer's "+" picker) - always searched,
    # on top of what the plan chooses.
    pinned_vdb_ids: list[str]

    # A "go further" follow-up (#219): the collections the previous answer left unexplored. Kept for the runs that
    # still carry them; a search now goes down every sub-collection, so nothing new is left unexplored.
    resume_from_vdb_ids: list[str]
    unexplored_vdb_ids: Annotated[list[str], operator.add]

    # Opt-in per message (chat composer toggle, off by default) - see Run.web_search_enabled.
    web_search_enabled: bool

    # --- questions to the user (#344) ---
    interactive: bool
    question_rounds: int
    # Set when the run ends on questions with options (the answer is then the same questions as text).
    questions: list[dict[str, Any]] | None
    # Set when the request was left open and nobody could be asked: the answer states the assumptions it made.
    must_assume: bool

    # --- permission barrier (§4) ---
    accessible_vdbs: list[dict[str, Any]]
    # What the plan was shown: the accessible collections, narrowed by the vector pre-filter when there are many.
    catalogue: list[dict[str, Any]]
    # What the user may edit / add a document to, loaded only when the message looks like a request to.
    edit_candidates: list[dict[str, Any]]
    create_candidates: list[dict[str, Any]]

    # --- the plan (one LLM call): what to do, with which tools, where ---
    plan: dict[str, Any]
    # The collections to search (the plan's and the pinned ones), each with its sub-collections by the backend;
    # empty means every accessible collection. `widened`: the search was already widened to all of them.
    scope_ids: list[str]
    widened: bool

    # --- delegated edit of a living document (#171) ---
    # {"document_id", "document_name", "collection_id", "instruction"} - or {"clarification": "..."} with what to tell
    # the user instead.
    edit_target: dict[str, Any] | None
    # What the edit / create path hands back with the answer so the chat can show the proposal next to it.
    edit_proposal: dict[str, Any] | None
    # {"collection_id", "collection_name", "title", "instruction"} - or {"clarification": "..."}.
    create_target: dict[str, Any] | None

    # --- understanding, kept in the shape the rest of the system reads (intent, complexity...) ---
    query_analysis: dict[str, Any]

    # --- research (independent tasks, in parallel) ---
    research_tasks: Annotated[list[ResearchTask], _merge_by_id]
    completed_task_ids: Annotated[list[str], operator.add]
    failed_task_ids: Annotated[list[str], operator.add]

    # --- evidence (§15-§16) ---
    evidence: Annotated[list[Evidence], operator.add]
    deduped_evidence: list[Evidence]

    # The gate's verdict on the evidence (code, no model).
    coverage_result: CoverageResult | None

    # --- answer (§21-§22) ---
    answer_context: dict[str, Any] | None
    answer: str | None
    citations: list[dict[str, Any]]
    answer_latency_ms: int | None
    answer_prompt_tokens: int | None
    answer_completion_tokens: int | None

    # --- grounding, checked after the answer is out ---
    needs_grounding: bool
    grounding_result: GroundingResult | None

    # Prompt version ids actually used by this run (§ issue #96 traceability).
    prompt_usages: Annotated[list[str], operator.add]

    # --- lifecycle (§30) ---
    execution_status: str
    cancelled: bool
