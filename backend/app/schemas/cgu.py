import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CguStatusOut(BaseModel):
    version: int | None
    content: str | None
    accepted: bool
    # True when this user already accepted an earlier version but not this one - the frontend
    # uses this to say "les CGU ont été mises à jour" instead of presenting a first-time screen
    # (§127).
    is_update: bool


class CguVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    content: str
    is_active: bool
    created_at: datetime


class CguVersionCreate(BaseModel):
    content: str
