import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    summary: str
    link: str | None
    data: dict
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    # What to ask for to get the older ones; None at the end of the list.
    next_cursor: str | None
    unread: int


class UnreadCountOut(BaseModel):
    count: int


class MarkReadIn(BaseModel):
    # Empty or missing: all of them.
    ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class PreferenceOut(BaseModel):
    type: str
    label: str
    description: str
    # In the application. The other channels are not offered.
    app: bool


class PreferenceIn(BaseModel):
    type: str
    app: bool


class PreferencesIn(BaseModel):
    preferences: list[PreferenceIn] = Field(max_length=50)
