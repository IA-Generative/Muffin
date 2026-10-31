import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.api_key import SCOPES


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    # Days until it expires; the default and the longest are settings. A key always expires.
    expires_in_days: int | None = Field(default=None, ge=1)

    def unknown_scopes(self) -> list[str]:
        return [scope for scope in self.scopes if scope not in SCOPES]


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    # `sk-muffin-` and the first characters: to tell the keys apart, never to use one.
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    """What creating a key answers - the only time the key itself is shown."""

    key: str
