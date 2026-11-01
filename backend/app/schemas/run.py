import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.image_generation import ImageOut
from app.schemas.question import Question, QuestionAnswer
from app.schemas.tool import ToolProposalOut


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
    # The assistant the chat is started with (#514): its collections (among those the caller may read) replace
    # `collection_ids`, its instructions are added to the answer's, and the run keeps its name and version.
    assistant_id: uuid.UUID | None = None
    # The images attached to this message for the model to read (#512): chosen in the composer beforehand
    # (`POST /api/images/attachments`), theirs, and sent with this one message only.
    image_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


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
    # The part of the answer written so far, while the run is still generating it - None otherwise.
    partial_answer: str | None = None
    # The edit of a living document this run delegated to the editing agent, if any (#171) - what
    # the chat needs to show the proposal next to the answer.
    edit_proposal: dict[str, Any] | None = None
    # Collections the agent selected but whose sub-collections it didn't explore within its budget
    # (#219) - what a follow-up with continue_exploration resumes from. None when nothing was left.
    unexplored_collection_ids: list[str] | None = None
    # The questions with options the run ended on instead of an answer (#344) - read from its message.
    questions: list[Question] | None = None
    # The assistant the run was made with, as it was then (#514).
    assistant_id: uuid.UUID | None = None
    assistant_name: str | None = None
    assistant_version: int | None = None
    # How many of the assistant's collections the caller cannot read, so the chat can say so.
    assistant_inaccessible_collections: int = 0
    # The requests to run a tool that changes data that this run made (#343): waiting for the person, or decided.
    tool_calls: list[ToolProposalOut] = []
    # The images this run made while answering (#518): shown with the answer, before it is a message the page reloads.
    images: list[ImageOut] = []
    error: str | None
    created_at: datetime
    updated_at: datetime
