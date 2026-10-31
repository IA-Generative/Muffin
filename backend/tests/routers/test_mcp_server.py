"""The MCP server (#467) over HTTP: who may call it, the tools it lists, and structured results."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import delete, update

from app import mcp_server
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.api_key import ApiKey
from app.models.collection import Collection, CollectionSettings
from app.schemas.api_key import ApiKeyCreate
from app.services import api_key_service
from app.services.api_key_service import ApiKeyService
from app.services.search_service import SearchService

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def _call(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, **({"params": params} if params else {})}


@pytest.fixture(scope="module")
async def server():
    """The session manager of the server runs once per process: one for all the tests of this module."""
    started, stop = asyncio.Event(), asyncio.Event()

    async def run() -> None:
        # Entered and left by the same task, which the server's task group requires.
        async with mcp_server.mcp.session_manager.run():
            started.set()
            await stop.wait()

    task = asyncio.create_task(run())
    await started.wait()
    yield
    stop.set()
    await task


@pytest.fixture
async def client(server):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(ApiKey))
        await session.commit()


class Keycloak:
    """The verifier of production, which only knows a bearer token: whose it is depends on the token."""

    def __call__(self, request):
        if request.headers.get("Authorization") != "Bearer good":
            raise HTTPException(401)
        return RequestContext(user_id="u", email="u@example.test", roles=[], is_admin=False)


async def test_a_call_without_a_token_is_refused(client, monkeypatch):
    monkeypatch.setattr(mcp_server, "TokenVerifier", Keycloak())

    response = await client.post("/api/mcp/", headers=HEADERS, json=_call("tools/list"))

    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"


async def test_a_session_cookie_is_not_a_token(client, monkeypatch):
    """A browser sends its cookie to any page: only an explicit bearer token calls the tools."""
    monkeypatch.setattr(mcp_server, "TokenVerifier", Keycloak())

    response = await client.post("/api/mcp/", headers=HEADERS, cookies={"session": "x"}, json=_call("tools/list"))

    assert response.status_code == 401


async def test_a_wrong_token_is_refused(client, monkeypatch):
    monkeypatch.setattr(mcp_server, "TokenVerifier", Keycloak())

    response = await client.post(
        "/api/mcp/", headers={**HEADERS, "Authorization": "Bearer bad"}, json=_call("tools/list")
    )

    assert response.status_code == 401


async def test_the_two_tools_are_listed_with_an_output_schema(client):
    response = await client.post("/api/mcp/", headers=HEADERS, json=_call("tools/list"))

    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"suggest_collections", "search"}
    assert tools["suggest_collections"]["inputSchema"]["required"] == ["query"]
    assert tools["search"]["inputSchema"]["required"] == ["query"]
    assert set(tools["search"]["inputSchema"]["properties"]) == {
        "query",
        "collection_ids",
        "model",
        "max_sub_queries",
        "max_collections",
        "limit",
    }
    assert "sub_queries" in tools["search"]["outputSchema"]["properties"]
    assert "collections" in tools["suggest_collections"]["outputSchema"]["properties"]


async def test_suggest_collections_returns_structured_content_for_the_caller_alone(client, monkeypatch):
    async with async_session_factory() as session:
        mine = Collection(owner_id="dev-user", name="Congés", description="Poser des congés")
        mine.settings = CollectionSettings(embedding_model="bge")
        theirs = Collection(owner_id="someone-else", name="Secret")
        theirs.settings = CollectionSettings(embedding_model="bge")
        session.add_all([mine, theirs])
        await session.commit()
        mine_id, theirs_id = mine.id, theirs.id

    async def search_collections(self, ids, query, limit):
        assert theirs_id not in ids
        return [(mine_id, 0.8)]

    monkeypatch.setattr(SearchService, "search_collections", search_collections)

    response = await client.post(
        "/api/mcp/",
        headers=HEADERS,
        json=_call("tools/call", {"name": "suggest_collections", "arguments": {"query": "congés", "limit": 3}}),
    )

    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {
        "query": "congés",
        "collections": [
            {
                "id": str(mine_id),
                "name": "Congés",
                "path": ["Congés"],
                "description": "Poser des congés",
                "score": 0.8,
                "url": f"http://localhost:5173/collections/{mine_id}",
            }
        ],
    }
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


async def test_a_search_in_a_collection_the_caller_cannot_read_is_an_error_not_a_result(client):
    async with async_session_factory() as session:
        theirs = Collection(owner_id="someone-else", name="Secret")
        theirs.settings = CollectionSettings(embedding_model="bge")
        session.add(theirs)
        await session.commit()
        theirs_id = theirs.id

    response = await client.post(
        "/api/mcp/",
        headers=HEADERS,
        json=_call("tools/call", {"name": "search", "arguments": {"query": "x", "collection_ids": [str(theirs_id)]}}),
    )

    result = response.json()["result"]
    assert result["isError"] is True and "structuredContent" not in result


async def test_search_returns_a_structured_result_by_sub_question(client, monkeypatch):
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Congés", description="d")
        collection.settings = CollectionSettings(embedding_model="bge")
        session.add(collection)
        await session.commit()
        collection_id = collection.id

    async def search_points(self, ids, query, limit):
        return []

    monkeypatch.setattr(SearchService, "search_points", search_points)

    response = await client.post(
        "/api/mcp/",
        headers=HEADERS,
        json=_call(
            "tools/call",
            {"name": "search", "arguments": {"query": "congés", "collection_ids": [str(collection_id)]}},
        ),
    )

    result = response.json()["result"]
    assert result["isError"] is False
    content = result["structuredContent"]
    assert content["query"] == "congés"
    assert [(sub["text"], [c["id"] for c in sub["collections"]], sub["sources"]) for sub in content["sub_queries"]] == [
        ("congés", [str(collection_id)], [])
    ]
    uuid.UUID(content["sub_queries"][0]["collections"][0]["id"])


# --- a personal API key (#521) ---


async def _api_key(monkeypatch, scopes: list[str]) -> str:
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))
    monkeypatch.setattr(mcp_server, "TokenVerifier", Keycloak())
    user = RequestContext(user_id="owner", email="owner@example.test", roles=[], is_admin=False)
    async with async_session_factory() as db:
        _, key = await ApiKeyService(db).create(user, ApiKeyCreate(name="script", scopes=scopes))
    return key


async def test_a_key_that_may_search_calls_the_tools(client, monkeypatch):
    key = await _api_key(monkeypatch, ["search"])

    response = await client.post(
        "/api/mcp/", headers={**HEADERS, "Authorization": f"Bearer {key}"}, json=_call("tools/list")
    )

    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {"suggest_collections", "search"}


async def test_a_key_made_for_something_else_does_not_call_the_tools(client, monkeypatch):
    key = await _api_key(monkeypatch, ["chat"])

    response = await client.post(
        "/api/mcp/", headers={**HEADERS, "Authorization": f"Bearer {key}"}, json=_call("tools/list")
    )

    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"


async def test_a_revoked_key_does_not_call_the_tools(client, monkeypatch):
    key = await _api_key(monkeypatch, ["search"])
    async with async_session_factory() as session:
        await session.execute(update(ApiKey).values(revoked_at=datetime.now(UTC)))
        await session.commit()

    response = await client.post(
        "/api/mcp/", headers={**HEADERS, "Authorization": f"Bearer {key}"}, json=_call("tools/list")
    )

    assert response.status_code == 401


async def test_a_key_that_asks_too_much_is_told_to_wait(client, monkeypatch):
    key = await _api_key(monkeypatch, ["search"])
    monkeypatch.setattr(api_key_service._settings, "API_KEY_RATE_LIMIT_PER_MINUTE", 1)
    headers = {**HEADERS, "Authorization": f"Bearer {key}"}

    first = await client.post("/api/mcp/", headers=headers, json=_call("tools/list"))
    second = await client.post("/api/mcp/", headers=headers, json=_call("tools/list"))

    assert first.status_code == 200
    assert second.status_code == 429 and second.headers["retry-after"] == "60"


async def test_a_key_that_looks_like_one_but_is_not_is_refused_and_not_tried_as_a_token(client, monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))
    monkeypatch.setattr(mcp_server, "TokenVerifier", Keycloak())

    response = await client.post(
        "/api/mcp/", headers={**HEADERS, "Authorization": "Bearer sk-muffin-good"}, json=_call("tools/list")
    )

    assert response.status_code == 401
