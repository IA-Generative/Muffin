import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Run(UUIDMixin, TimestampMixin, Base):
    """A research agent run. The source of truth for its lifecycle - the
    Celery task executing it (see backend/app/core/agent_tasks.py) reads and
    writes this row rather than keeping state in worker memory, so a worker
    restart, a resume after HITL, or a status check never depend on the
    task's own process being alive."""

    __tablename__ = "runs"

    # Keycloak subject (sub); identity always comes from the authenticated
    # request context, never from the LLM or the run's own payload.
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # Strong, non-nullable link to the user message that triggered this run -
    # a run always exists *because* of one specific message, never floating
    # free in a conversation. conversation_id is kept alongside it (instead
    # of only reachable via message.conversation_id) purely so "list runs in
    # this conversation" doesn't need a join; it must always equal
    # message.conversation_id (enforced in RunRepository.create, which loads
    # the message to derive it rather than trusting a caller-supplied value).
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    celery_task_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)

    query: Mapped[str] = mapped_column(Text, nullable=False)
    # Collections explicitly attached via the chat composer's "+" picker (§ user-pinned
    # collections) - stored as plain strings, same reasoning as citations below: read back
    # as-is by the worker, never queried/filtered on at the SQL level.
    pinned_collection_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Snapshot of RequestContext.groups at run creation time - the worker's load_accessible_vdbs
    # node needs this to resolve group-shared collections (see CollectionRepository.
    # list_all_accessible), and has no session/token of its own to read it from live. A snapshot,
    # not a live lookup, same tradeoff as pinned_collection_ids above: a group membership change
    # mid-run is not expected to retroactively change what an already-running query can reach.
    user_groups: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Opt-in per message (chat composer toggle, see RunCreate.web_search_enabled) - snapshotted
    # here for the same reason as the two fields above: the worker only ever reads this run row,
    # never a live per-request flag, so whatever was true when the run was created is what it acts on.
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether someone reads the answer as it comes and can reply to a question (#344). False for a run
    # started by a program (MCP, A2A): it is never asked questions it could not answer.
    interactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # The assistant the chat was started with (#514), kept as it was then so that a run can say which instructions
    # produced its answer even after the assistant is changed or deleted: no foreign key on purpose.
    assistant_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    assistant_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assistant_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assistant_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The optional tools that assistant turns off, as they were then.
    assistant_disabled_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # The assistants this run may consult (#531), as they were when it was made: [{id, name, description,
    # collection_ids, disabled_tools}], the collections being those the person may read. Fixed here, in code, so the
    # agent
    # only ever picks among them and never reaches a collection that was not worked out for this person.
    consultable_assistants: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Whether the search stays within the collections the run was given instead of going on to the others the person
    # may read (an assistant's, or a model of the OpenAI-compatible API). The planner can then narrow, never widen.
    scope_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # What the guardrails on the input did to this run (#516): `blocked`, `redacted`, `warned`, or None. The text of the
    # request is not here: what the model saw instead of it is `Message.redacted_content`, and the words shown to the
    # person (a refusal, a warning) are `guardrail_notice`.
    guardrail_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    guardrail_notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether the person's memory plays in this run (#282): `on`, `temporary` (the person turned it off for this
    # conversation), or `unavailable` (an assistant, a routine or the OpenAI-compatible API: the memory is for the
    # personal chat). How many of its items shaped the answer is `memory_used` - their content is nowhere on the run.
    memory_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="on", server_default="on")
    memory_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Whether the requesting user was a platform administrator, and how to show them ("Jean D."),
    # snapshotted like user_groups: the research agent acts on the user's behalf from this row alone
    # (it has no session), e.g. to ask the backend to start an edit of a living document (#171) -
    # who may do that is decided backend-side from this snapshot, never from anything the agent says.
    user_is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    user_display: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False, default=RunStatus.QUEUED
    )
    # Cooperative cancellation flag - nodes check this at key points instead
    # of relying solely on Celery's revoke(terminate=True), which can't
    # interrupt a node already mid-flight or a WAITING_FOR_USER run that has
    # no active task to terminate at all.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    current_node: Mapped[str | None] = mapped_column(String, nullable=True)
    current_activity: Mapped[str | None] = mapped_column(String, nullable=True)

    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Free-form snapshots of LangGraph state that need to survive a worker
    # restart or a HITL pause - research plan/tasks, budget, pending human
    # action. Kept as JSONB rather than dedicated columns/tables at this
    # stage: their shape is still expected to move as the graph (Étape 4+)
    # is built out, and a schema migration per shape change would slow that
    # down for no benefit yet - promote a key to a real column/table once
    # its shape has actually stabilized.
    research_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pending_human_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Set when this run delegated an edit of a living document to the editing agent (#171):
    # {"collection_id", "document_id", "document_name"} - what the chat needs to show the proposal
    # next to the answer. The proposal itself (draft, preview, verdict) lives in DocumentDraft.
    edit_proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Final claim-by-claim grounding check (see backend/app/agent/graph/nodes/
    # validate_grounding.py's GroundingResult) - null until the run completes with an answer,
    # stays null on a failed/cancelled/waiting run. Not recomputed here: this is the same verdict
    # already used internally to decide whether to loop through targeted_research, just persisted
    # so it can be queried after the fact instead of only living in worker memory during the run.
    grounding_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    grounding_unsupported_claims: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # How many targeted_research retries the grounding loop triggered before settling on the
    # final verdict above (bounded by MAX_GROUNDING_RESEARCHES) - a run that needed several
    # retries to become grounded is a weaker result than one that was grounded on the first pass.
    grounding_research_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Sub-collection exploration (#219). The research agent descends the collection tree level by
    # level within a budget; `unexplored_collection_ids` are the collections it selected but whose
    # sub-collections it didn't get to - where a "go further" follow-up resumes from. Plain strings,
    # same reasoning as pinned_collection_ids. `continue_exploration` marks such a follow-up (the
    # chat's "go further" button), snapshotted like web_search_enabled.
    unexplored_collection_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    continue_exploration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.created_at"
    )


class RunEvent(UUIDMixin, TimestampMixin, Base):
    """One structured event per significant state change (§20 of the
    architecture brief) - the UI reconstructs real progress from these
    rather than a fabricated progress bar."""

    __tablename__ = "run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    # Nullable: run-level events (run_started, run_completed, ...) aren't
    # correlated to a specific research task.
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")
