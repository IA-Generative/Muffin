"""Muffin as the client of an A2A agent a user added (#a2a): its agent card, and a message sent to it.

The Agent2Agent protocol (https://a2a-protocol.org) publishes an agent card (name, description, skills) at a
well-known address and is talked to over JSON-RPC: `message/send`, with the question as one message, answered with a
message or a task whose last message or artifacts hold the answer. Muffin has no notion of the agent's individual
skills to call by name - unlike an MCP server, which lists several tools, one A2A agent is imported as **one** tool
(`list_tools` below always returns exactly one), called by sending it the model's question as free text.

Same rules as `mcp_client.py`: everything that comes back is data from a third party, bounded, never run, and the
address is checked before each connection (app/core/url_guard.py)."""

import uuid
from typing import Any

import httpx2

from app.config import ToolSettings
from app.core.url_guard import ensure_public
from app.services.tools.mcp_client import RemoteResult, RemoteTool, ToolServerError

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ToolSettings()

# Where the agent card may be, tried in order (the current path of the spec, then the one it replaced).
_CARD_PATHS = ("/.well-known/agent-card.json", "/.well-known/agent.json")
_DESCRIPTION_MAX_CHARS = 2000
_NAME_MAX_CHARS = 128
# The name of the single tool an agent is imported as - there being only one, it needs no other.
TOOL_NAME = "demander"


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _fetch_card(url: str, token: str | None) -> dict[str, Any]:
    base = url.rstrip("/")
    async with httpx2.AsyncClient(
        headers=_headers(token), timeout=_settings.TOOLS_CALL_TIMEOUT_SECONDS, follow_redirects=False
    ) as http:
        for path in _CARD_PATHS:
            try:
                response = await http.get(base + path)
            except Exception:  # noqa: BLE001 - the next path, or the generic error below, follows
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception:  # noqa: BLE001
                    continue
    raise ToolServerError("serveur_injoignable", "La carte de l'agent n'a pas été trouvée.")


def _skills_text(card: dict[str, Any]) -> str:
    skills = card.get("skills")
    if not isinstance(skills, list) or not skills:
        return ""
    lines = [
        str(skill.get("description") or skill.get("name") or "")
        for skill in skills
        if isinstance(skill, dict) and (skill.get("description") or skill.get("name"))
    ]
    return " Compétences : " + "; ".join(lines) if lines else ""


async def list_tools(url: str, token: str | None) -> list[RemoteTool]:
    """What the agent card describes, as the one tool calling it is (#a2a): its name and description, with its
    skills summarised into the description so the model knows when to use it."""
    await _checked(url)
    try:
        card = await _fetch_card(url, token)
    except ToolServerError:
        raise
    except Exception as error:
        raise ToolServerError("serveur_injoignable", f"Le serveur n'a pas répondu ({type(error).__name__}).") from error
    name = str(card.get("name") or "").strip()[:_NAME_MAX_CHARS]
    if not name:
        raise ToolServerError("serveur_injoignable", "La carte de l'agent n'a pas de nom.")
    description = f"Demande à l'agent « {name} » (A2A) : {card.get('description') or ''}".strip()
    description += _skills_text(card)
    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "La question ou la demande à transmettre à l'agent"}
        },
        "required": ["message"],
    }
    return [
        RemoteTool(
            name=TOOL_NAME,
            description=description[:_DESCRIPTION_MAX_CHARS],
            input_schema=schema,
            # Handing the question to another agent is not run by itself (#a2a): like a tool that changes data, it
            # becomes a request the person decides (ToolService._propose) - they see which agent and what is asked
            # before anything leaves Muffin.
            side_effect=True,
        )
    ]


def _extract_text(result: dict[str, Any]) -> str:
    """A `message/send` answers with a Message (its own `parts`) or a Task (whose last status message, then its
    artifacts, hold the parts) - either way, only the text parts are read."""
    parts = result.get("parts")
    if not isinstance(parts, list):
        parts = ((result.get("status") or {}).get("message") or {}).get("parts")
    if not isinstance(parts, list):
        artifacts = result.get("artifacts") or []
        parts = [part for artifact in artifacts if isinstance(artifact, dict) for part in artifact.get("parts") or []]
    if not isinstance(parts, list):
        return ""
    return "\n".join(str(part.get("text")) for part in parts if isinstance(part, dict) and part.get("kind") == "text")


async def call_tool(url: str, token: str | None, _name: str, arguments: dict[str, Any]) -> RemoteResult:
    """Sends `arguments["message"]` to the agent (`message/send`) and reads back its answer. `_name` is unused: there
    is only the one tool an A2A server has (`TOOL_NAME`)."""
    await _checked(url)
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": str(arguments.get("message", ""))}],
                "messageId": str(uuid.uuid4()),
            }
        },
    }
    try:
        async with httpx2.AsyncClient(
            headers=_headers(token), timeout=_settings.TOOLS_CALL_TIMEOUT_SECONDS, follow_redirects=False
        ) as http:
            response = await http.post(url, json=payload)
        body = response.json()
    except TimeoutError as error:
        raise ToolServerError("delai_depasse", "Le serveur a mis trop de temps à répondre.") from error
    except Exception as error:
        raise ToolServerError("serveur_injoignable", f"Le serveur n'a pas répondu ({type(error).__name__}).") from error
    limit = _settings.TOOLS_OUTPUT_MAX_CHARS
    if isinstance(body, dict) and body.get("error"):
        message = str((body.get("error") or {}).get("message") or "L'agent a répondu par une erreur.")
        return RemoteResult(text=message[:limit], is_error=True, truncated=False)
    text = _extract_text((body or {}).get("result") or {}) if isinstance(body, dict) else ""
    return RemoteResult(text=text[:limit], is_error=False, truncated=len(text) > limit)


async def _checked(url: str) -> None:
    from app.core.url_guard import UrlRefusedError

    try:
        await ensure_public(url)
    except UrlRefusedError as error:
        raise ToolServerError("url_refusee", str(error)) from error
