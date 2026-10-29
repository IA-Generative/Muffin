import uuid

from pydantic import BaseModel, Field


class GroupSyncIn(BaseModel):
    """A group as the other system has it (#453): the synchronisation sends it whole, members included."""

    name: str = Field(min_length=1)
    description: str = ""
    # Keycloak subjects. The members the other system could not tie to one are left out by the worker.
    member_ids: list[str] = Field(default_factory=list)


class GroupSyncOut(BaseModel):
    id: uuid.UUID
    created: bool
    members_added: int
    members_removed: int
