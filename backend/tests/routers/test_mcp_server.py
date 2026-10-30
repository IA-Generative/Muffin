"""The MCP server (#467) over HTTP: who may call it, the tools it lists, and structured results."""

import asyncio
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app import mcp_server
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
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
            {"id": str(mine_id), "name": "Congés", "path": ["Congés"], "description": "Poser des congés", "score": 0.8}
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
