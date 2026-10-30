import uuid

from pydantic import BaseModel, Field

from app.models.collection import SharePermission


class UserShareIn(BaseModel):
    subject_id: str = Field(min_length=1, description="Keycloak subject of the user the collection is read by")
    email: str = Field(default="", description="Only to show a masked hint of who it is shared with")
    permission: SharePermission = SharePermission.READ


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
    # Among them, those that may also write (#454).
    write_group_external_ids: list[str] = Field(default_factory=list)
    # What is wrong with the vectors the other system holds for it - another model or length than it is said to have
    # (#453) - for the administrators' page (#466).
    vector_problems: list[str] = Field(default_factory=list)


class CollectionSyncOut(BaseModel):
    id: uuid.UUID
    created: bool
    shares_added: int
    shares_removed: int
    # Shares that were already there and now let read, or write, differently.
    shares_updated: int = 0
    # Groups the collection is shared with that Muffin has no copy of (yet): no share is made for them.
    unknown_groups: list[str]
    # Muffin took the collection over (#462): nothing was written.
    skipped: bool = False
