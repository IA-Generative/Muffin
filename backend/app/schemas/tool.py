import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Visibility = Literal["private", "groups", "all"]
AuthMode = Literal["none", "bearer"]


class ToolServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    auth_mode: AuthMode = "none"
    # The token of a `bearer` server. Kept encrypted, used to call the server, never given back.
    token: str | None = Field(default=None, max_length=4096)
    visibility: Visibility = "private"
    group_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a name is needed")
        return value.strip()


class ToolServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    auth_mode: AuthMode | None = None
    # Left out: the token stays. Sent: it is replaced.
    token: str | None = Field(default=None, max_length=4096)
    visibility: Visibility | None = None
    group_ids: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None


class ToolOut(BaseModel):
    # What the chat refers to a tool by: `internal.calculatrice`, or the id of the tool of a server.
    ref: str
    name: str
    description: str
    input_schema: dict[str, Any]
    server_id: uuid.UUID | None = None
    server_name: str | None = None
    side_effect: bool = False
    # False when the person removed it for this conversation. A tool that changes data is available too: it is
    # proposed to the person, who decides (`side_effect`), never run by itself.
    available: bool = True
    # Why a tool is not available, in words: "retiré pour cette conversation".
    reason: str | None = None


class ToolHitOut(ToolOut):
    """A tool found by what it does (#530): the tool as listed, how close it is to the question, and how it was matched
    - `hybrid` (the vector and the words) or `lexical` (the words alone, when the index cannot be used)."""

    score: float
    match: Literal["hybrid", "lexical"]


class ToolServerOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    auth_mode: AuthMode
    has_token: bool
    visibility: Visibility
    group_ids: list[str]
    enabled: bool
    is_owner: bool
    last_synced_at: datetime | None
    last_error: str | None
    tools: list[ToolOut]


class ToolCallRequest(BaseModel):
    """What the agent asks of the backend, on behalf of a person."""

    user_id: str
    groups: list[str] = Field(default_factory=list)
    conversation_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    ref: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    ok: bool
    # `ok`, or a code that does not change: quota_depasse, outil_indisponible, arguments_invalides,
    # confirmation_demandee, url_refusee, serveur_injoignable, delai_depasse, erreur_outil.
    code: str
    text: str
    truncated: bool = False
    tool_name: str = ""
    server_name: str | None = None
    # Set when the call became a request waiting for the person's decision (code `confirmation_demandee`).
    proposal_id: uuid.UUID | None = None
    arguments: dict[str, Any] | None = None


class ToolDefinitionsRequest(BaseModel):
    user_id: str
    groups: list[str] = Field(default_factory=list)
    conversation_id: uuid.UUID | None = None


class ConversationToolsUpdate(BaseModel):
    """The tools a person removes for a conversation: the whole list, replacing the previous one."""

    disabled_refs: list[str] = Field(default_factory=list, max_length=200)


class RunToolDefinitionsRequest(BaseModel):
    """What the agent asks to be told: the tools the person of this run may use now. The person, their groups and the
    conversation are read from the run, never from what the agent says."""

    run_id: uuid.UUID


class RunToolCallRequest(BaseModel):
    run_id: uuid.UUID
    ref: str = Field(max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)


ProposalStatus = Literal["pending", "approved", "refused", "executed", "failed", "superseded", "expired"]


class ToolProposalOut(BaseModel):
    """A tool the assistant asks to run, shown to the person who decides - with the arguments they agree to."""

    id: uuid.UUID
    run_id: uuid.UUID | None
    conversation_id: uuid.UUID
    tool_name: str
    server_name: str | None
    arguments: dict[str, Any]
    status: ProposalStatus
    created_at: datetime
    decided_at: datetime | None
    result_code: str | None


class ToolDecision(BaseModel):
    """The person's answer for the requests of one turn: all of them are authorised, or all refused."""

    approve: bool
