"""Muffin as the client of an MCP server a user added (#343): what the server offers, and a call to one of its tools.

Everything that comes back is data from a third party: its descriptions are read by a model, its answers go into a
reply. So they are bounded (length of a description, size of a schema, characters of an answer), never run, and the
address is checked for what it resolves to before each connection (app/core/url_guard.py)."""

from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import ToolSettings
from app.core.url_guard import ensure_public

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ToolSettings()

_DESCRIPTION_MAX_CHARS = 2000
_SCHEMA_MAX_CHARS = 8000
_NAME_MAX_CHARS = 128


class ToolServerError(Exception):
    """The server could not be used. `code` is stable (for the journal and the model); the message is for the person."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RemoteTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    side_effect: bool


@dataclass(frozen=True)
class RemoteResult:
    text: str
    is_error: bool
    truncated: bool


def _transport(url: str, token: str | None):  # noqa: ANN202
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # No redirect is followed to somewhere else: the transport itself only follows one that stays on the same origin.
    http = httpx2.AsyncClient(headers=headers, timeout=_settings.TOOLS_CALL_TIMEOUT_SECONDS, follow_redirects=False)
    return streamable_http_client(url, http_client=http)


def _bounded_schema(schema: Any) -> dict[str, Any]:
    """The schema of a tool's arguments if it is an object schema of a sensible size - otherwise an empty one (the
    tool is
    then called with no argument checking beyond the server's own)."""
    import json

    if not isinstance(schema, dict) or len(json.dumps(schema, default=str)) > _SCHEMA_MAX_CHARS:
        return {"type": "object"}
    return schema


async def list_tools(url: str, token: str | None) -> list[RemoteTool]:
    await _checked(url)
    try:
        async with Client(_transport(url, token), read_timeout_seconds=_settings.TOOLS_CALL_TIMEOUT_SECONDS) as client:
            listed = await client.list_tools()
    except Exception as error:
        raise ToolServerError("serveur_injoignable", f"Le serveur n'a pas répondu ({type(error).__name__}).") from error
    tools = []
    for tool in listed.tools[: _settings.TOOLS_PER_SERVER_MAX]:
        if not tool.name or len(tool.name) > _NAME_MAX_CHARS:
            continue
        annotations = tool.annotations
        # Not known to be read-only means it may change something: that is the safe reading.
        read_only = bool(annotations and annotations.read_only_hint is True)
        tools.append(
            RemoteTool(
                name=tool.name,
                description=(tool.description or tool.title or "")[:_DESCRIPTION_MAX_CHARS],
                input_schema=_bounded_schema(tool.input_schema),
                side_effect=not read_only,
            )
        )
    return tools


async def call_tool(url: str, token: str | None, name: str, arguments: dict[str, Any]) -> RemoteResult:
    await _checked(url)
    try:
        async with Client(_transport(url, token), read_timeout_seconds=_settings.TOOLS_CALL_TIMEOUT_SECONDS) as client:
            result = await client.call_tool(name, arguments, read_timeout_seconds=_settings.TOOLS_CALL_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise ToolServerError("delai_depasse", "Le serveur a mis trop de temps à répondre.") from error
    except Exception as error:
        raise ToolServerError("serveur_injoignable", f"Le serveur n'a pas répondu ({type(error).__name__}).") from error
    parts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    if len(parts) < len(result.content):
        parts.append("[contenu non textuel omis]")
    text = "\n".join(parts)
    limit = _settings.TOOLS_OUTPUT_MAX_CHARS
    return RemoteResult(text=text[:limit], is_error=bool(result.is_error), truncated=len(text) > limit)


async def _checked(url: str) -> None:
    from app.core.url_guard import UrlRefusedError

    try:
        await ensure_public(url)
    except UrlRefusedError as error:
        raise ToolServerError("url_refusee", str(error)) from error
