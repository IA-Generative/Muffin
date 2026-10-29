import uuid

from pydantic import BaseModel, Field


class UserShareIn(BaseModel):
    subject_id: str = Field(min_length=1, description="Keycloak subject of the user the collection is read by")
    email: str = Field(default="", description="Only to show a masked hint of who it is shared with")


class CollectionSyncIn(BaseModel):
    """A collection as the other system has it (#453): the synchronisation sends it whole, with who may read it."""

    name: str = Field(min_length=1)
    description: str = ""
    owner_id: str = Field(min_length=1, description="Keycloak subject of the owner")
    embedding_model: str = Field(min_length=1, description="The model the vectors the other system made were made with")
    public: bool = False
    user_shares: list[UserShareIn] = Field(default_factory=list)
    # Ids, in the other system, of the groups it is shared with: they must have been synchronised already.
    group_external_ids: list[str] = Field(default_factory=list)


class CollectionSyncOut(BaseModel):
    id: uuid.UUID
    created: bool
    shares_added: int
    shares_removed: int
    # Groups the collection is shared with that Muffin has no copy of (yet): no share is made for them.
    unknown_groups: list[str]
