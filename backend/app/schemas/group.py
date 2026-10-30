import uuid

from pydantic import BaseModel, Field, model_validator


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


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    # Where it comes from: made here, or copied from Open WebUI (#453) - then only the synchronisation changes it.
    source: str
    is_owner: bool
    # May rename it, delete it and manage its members: its owner or an administrator - never a copied group.
    can_manage: bool
    # People who are in it. The invitations that wait for someone to sign in are counted for those who manage it.
    member_count: int
    pending_count: int = 0


class MemberAdd(BaseModel):
    """Who to add: an email - never looked up, an invitation that turns into a member when that person signs
    in, like a collection share - or the Keycloak subject of someone, who is a member at once."""

    email: str | None = Field(default=None, min_length=3)
    user_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> "MemberAdd":
        if (self.email is None) == (self.user_id is None):
            raise ValueError("give either an email or a user_id")
        return self


class MemberOut(BaseModel):
    id: uuid.UUID
    status: str
    # A name to show - never a Keycloak subject. For an invitation, the masked email ("j***@e***.com").
    display: str
