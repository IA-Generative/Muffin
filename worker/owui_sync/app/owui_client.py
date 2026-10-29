"""Open WebUI's REST API, read-only (#453): what the synchronisation lists to copy into Muffin.

Written against Open WebUI 0.12.5 (docs/owui-test-instance.md): the users, the knowledge bases and their files
are paginated (`?page=N`, an empty page is the end), the groups are not. A transient failure - the network, a
429 or a 5xx - is tried again with a growing pause; any other error status fails at once, with the response in
the message, since trying again would not change it (a wrong key, a route this version does not have).
"""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OwuiError(Exception):
    """Open WebUI could not be read: the message says which call and why."""


class _Model(BaseModel):
    # Open WebUI sends far more than the synchronisation needs, and adds fields from one version to the next.
    model_config = ConfigDict(extra="ignore")


class OwuiAccessGrant(_Model):
    """One line of a resource's `access_grants`: who may do what. `principal_id` is `*` for everyone."""

    principal_type: str
    principal_id: str
    permission: str


class OwuiUser(_Model):
    id: str
    email: str
    name: str
    role: str = "user"


class OwuiGroup(_Model):
    id: str
    name: str
    description: str | None = None
    user_id: str | None = None
    parent_group_id: str | None = None


class OwuiFile(_Model):
    id: str
    user_id: str | None = None
    filename: str
    hash: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None
    updated_at: int | None = None


class OwuiKnowledge(_Model):
    id: str
    user_id: str
    name: str
    description: str | None = None
    access_grants: list[OwuiAccessGrant] = Field(default_factory=list)
    created_at: int | None = None
    updated_at: int | None = None


class OwuiClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 4,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            base_url=(base_url or settings.OWUI_BASE_URL).rstrip("/"),
            headers={"Authorization": f"Bearer {api_key or settings.OWUI_API_KEY}"},
            timeout=60.0,
            transport=transport,
        )
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(path, params=params)
            except httpx.TransportError as error:
                failure = f"{type(error).__name__}: {error}"
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    if response.is_error:
                        raise OwuiError(f"GET {path} -> {response.status_code}: {response.text[:200]}")
                    return response.json()
                failure = f"status {response.status_code}"
            if attempt == self._max_attempts:
                raise OwuiError(f"GET {path} failed after {attempt} attempts ({failure})")
            pause = self._backoff_seconds * 2 ** (attempt - 1)
            logger.warning(
                "GET {} failed ({}), attempt {}/{}: again in {}s", path, failure, attempt, self._max_attempts, pause
            )
            self._sleep(pause)
        raise AssertionError("unreachable")

    def _pages(self, path: str, key: str) -> Iterator[list[dict]]:
        """The pages of a paginated listing, one list per page; `key` is where the page holds its items."""
        page = 1
        while True:
            items = self._get(path, {"page": page})[key]
            if not items:
                return
            yield items
            page += 1

    def users(self) -> Iterator[OwuiUser]:
        for items in self._pages("/api/v1/users/", "users"):
            yield from (OwuiUser.model_validate(item) for item in items)

    def groups(self) -> list[OwuiGroup]:
        return [OwuiGroup.model_validate(item) for item in self._get("/api/v1/groups/")]

    def group_member_ids(self, group_id: str) -> list[str]:
        """The users that belong to the group itself, not through one of its sub-groups."""
        return self._get(f"/api/v1/groups/id/{group_id}/export")["user_ids"]

    def knowledge_bases(self) -> Iterator[OwuiKnowledge]:
        for items in self._pages("/api/v1/knowledge/", "items"):
            yield from (OwuiKnowledge.model_validate(item) for item in items)

    def knowledge_files(self, knowledge_id: str) -> Iterator[OwuiFile]:
        for items in self._pages(f"/api/v1/knowledge/{knowledge_id}/files", "items"):
            yield from (OwuiFile.model_validate(item) for item in items)
