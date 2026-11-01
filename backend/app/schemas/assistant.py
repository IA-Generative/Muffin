import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.agent.graph.services.tool_guide import OPTIONAL_TOOLS
from app.models.collection import CollectionVisibility

MAX_INSTRUCTIONS_CHARS = 4000
MAX_COLLECTIONS = 50
MAX_SUGGESTIONS = 6
MAX_SUGGESTION_CHARS = 200


def _known_tools(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    unknown = sorted(set(values) - OPTIONAL_TOOLS)
    if unknown:
        raise ValueError(f"unknown or required tool: {', '.join(unknown)}")
    return list(dict.fromkeys(values))


def _clean_suggestions(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [value.strip() for value in values if value.strip()]


class AssistantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=16)
    color: str = Field(default="", max_length=16)
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS_CHARS)
    hide_instructions: bool = False
    collection_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_COLLECTIONS)
    include_descendants: bool = True
    web_search_allowed: bool = False
    # Optional tools of the agent this assistant does not use. The graph is the same one.
    disabled_tools: list[str] = Field(default_factory=list)
    # Typed by hand: never generated from what the collections hold.
    suggestions: list[str] = Field(default_factory=list, max_length=MAX_SUGGESTIONS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a name is needed")
        return value.strip()

    @field_validator("disabled_tools")
    @classmethod
    def _tools(cls, values: list[str]) -> list[str]:
        return _known_tools(values) or []

    @field_validator("suggestions")
    @classmethod
    def _suggestions(cls, values: list[str]) -> list[str]:
        if any(len(value) > MAX_SUGGESTION_CHARS for value in values):
            raise ValueError(f"a suggested question may hold {MAX_SUGGESTION_CHARS} characters at most")
        return _clean_suggestions(values) or []


class AssistantUpdate(BaseModel):
    """Only what is sent changes."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS_CHARS)
    hide_instructions: bool | None = None
    collection_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_COLLECTIONS)
    include_descendants: bool | None = None
    web_search_allowed: bool | None = None
    disabled_tools: list[str] | None = None
    suggestions: list[str] | None = Field(default=None, max_length=MAX_SUGGESTIONS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("a name is needed")
        return value.strip() if value is not None else None

    @field_validator("disabled_tools")
    @classmethod
    def _tools(cls, values: list[str] | None) -> list[str] | None:
        return _known_tools(values)

    @field_validator("suggestions")
    @classmethod
    def _suggestions(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and any(len(value) > MAX_SUGGESTION_CHARS for value in values):
            raise ValueError(f"a suggested question may hold {MAX_SUGGESTION_CHARS} characters at most")
        return _clean_suggestions(values)


class AssistantVisibilityUpdate(BaseModel):
    visibility: CollectionVisibility


class AssistantCollectionOut(BaseModel):
    id: uuid.UUID
    name: str


class AssistantOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    icon: str
    color: str
    # None for someone who only reads an assistant whose author hides the instructions: they apply all the same.
    instructions: str | None
    instructions_hidden: bool
    hide_instructions: bool
    # Only the collections the caller may read, with their names. The others are only counted - never named.
    collections: list[AssistantCollectionOut]
    inaccessible_collection_count: int
    include_descendants: bool
    web_search_allowed: bool
    disabled_tools: list[str]
    suggestions: list[str]
    visibility: CollectionVisibility
    version: int
    is_owner: bool
    can_edit: bool
    # How many people and groups it is shared with - for its author only.
    share_count: int = 0
    created_at: datetime
    updated_at: datetime
