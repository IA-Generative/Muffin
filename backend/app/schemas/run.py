import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.question import Question, QuestionAnswer


class RunCreate(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    # Collections explicitly attached via the chat composer's "+" picker - always searched
    # regardless of what the agent's own VDB relevance routing would have picked on its own.
    collection_ids: list[uuid.UUID] | None = None
    # Whether pinning a collection also pins the sub-collections below it (#220), resolved once
    # when the run is created - the "include sub-collections" checkbox of the picker, on by
    # default. Capped by PINNED_DESCENDANTS_LIMIT, see RunService.create_run.
    include_descendants: bool = True
    # Opt-in, per message (the chat composer's web-search toggle, off by default) - never
    # implied by anything else. Gates both whether the planner is even told a "web_search" tool
    # exists and whether research_task will actually run it (see worker/agent_execution).
    web_search_enabled: bool = False
    # "Go further" (#219): resume the sub-collection exploration where the previous answer of
    # this conversation stopped (its RunOut.unexplored_collection_ids), instead of starting
    # again from the top-level collections.
    continue_exploration: bool = False
    # Answering the questions the assistant asked (#344): the run that asked them (its answer is the message
    # that holds them), and the answer to each. The query is the answer as text, which is what the user's
    # message says in the thread.
    answers_run_id: uuid.UUID | None = None
    answers: list[QuestionAnswer] | None = None
    # False for a run started by a program (MCP, A2A): no one is there to answer a question.
    interactive: bool = True


class RunResumeRequest(BaseModel):
    answer: str


class RunEventOut(BaseModel):
    id: uuid.UUID
    task_id: str | None
    type: str
    data: dict[str, Any] | None
    created_at: datetime


class RunOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    query: str
    status: str
    cancel_requested: bool
    current_node: str | None
    current_activity: str | None
    plan_version: int
    replan_count: int
    pending_human_action: dict[str, Any] | None
    answer: str | None
    citations: list[dict[str, Any]] | None
    # The edit of a living document this run delegated to the editing agent, if any (#171) - what
    # the chat needs to show the proposal next to the answer.
    edit_proposal: dict[str, Any] | None = None
    # Collections the agent selected but whose sub-collections it didn't explore within its budget
    # (#219) - what a follow-up with continue_exploration resumes from. None when nothing was left.
    unexplored_collection_ids: list[str] | None = None
    # The questions with options the run ended on instead of an answer (#344) - read from its message.
    questions: list[Question] | None = None
    error: str | None
    created_at: datetime
    updated_at: datetime
