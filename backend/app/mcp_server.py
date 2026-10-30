"""The MCP server (#467): Muffin's search offered to MCP clients, with the Keycloak the REST API uses.

Two tools, both reading only the collections the caller can read - the same as in the chat - and writing no answer:
`suggest_collections` (which collections a question is about) and `search` (the sources for a question, by
sub-question). Both return structured data, with an output schema."""

import contextlib
import uuid
from contextvars import ContextVar
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security.factory import AllowAllAccess, RequestContext, TokenVerifier
from app.db import async_session_factory
from app.repositories.group_repository import GroupRepository
from app.schemas.mcp import SearchResult, SuggestedCollections
from app.services.mcp_search_service import McpSearchService

# Who is calling, set by the middleware below for the tools to read: a tool takes only what the client sends.
_caller: ContextVar[RequestContext] = ContextVar("mcp_caller")

mcp = MCPServer(
    "Muffin",
    instructions=(
        "Search the document collections you can read. `suggest_collections` tells which collections a question is "
        "about; `search` splits a question into sub-questions and returns, for each, the collections searched and "
        "the best sources. Neither writes an answer."
    ),
)


@mcp.tool()
async def suggest_collections(
    query: Annotated[str, Field(description="The question or topic to find collections for", min_length=1)],
    limit: Annotated[int | None, Field(description="How many collections at most (default 5, never over 20)")] = None,
) -> SuggestedCollections:
    """The collections most likely to hold the answer to a question, from the descriptions of the collections you
    can read. No model reads the question: it is compared to the descriptions."""
    async with async_session_factory() as db:
        return await McpSearchService(db).suggest_collections(_caller.get(), query, limit)


@mcp.tool()
async def search(
    query: Annotated[str, Field(description="The question", min_length=1)],
    collection_ids: Annotated[
        list[uuid.UUID] | None,
        Field(description="Search only these collections. Left out, each sub-question picks its own best ones"),
    ] = None,
    model: Annotated[
        str | None, Field(description="The chat model that splits the question (default: the server's)")
    ] = None,
    max_sub_queries: Annotated[int | None, Field(description="At most this many sub-questions (default 4)")] = None,
    max_collections: Annotated[
        int | None, Field(description="At most this many collections per sub-question (default 3)")
    ] = None,
    limit: Annotated[int | None, Field(description="At most this many sources per sub-question (default 5)")] = None,
) -> SearchResult:
    """Splits the question into sub-questions and, for each one, finds the best sources in the collections: passages
    of documents, questions already answered, and document summaries, with their document, page and score. Writes
    no answer."""
    async with async_session_factory() as db:
        return await McpSearchService(db).search(
            _caller.get(), query, collection_ids, model, max_sub_queries, max_collections, limit
        )


class CallerMiddleware:
    """Knows the caller from their Keycloak bearer token - not the session cookie, which a browser sends on its own
    to any page - and refuses the request otherwise. The caller's Muffin groups are added to their token's."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        open_access = isinstance(TokenVerifier, AllowAllAccess)
        try:
            if not open_access and not request.headers.get("Authorization", "").startswith("Bearer "):
                raise PermissionError
            context = TokenVerifier(request)
        except Exception:
            response = JSONResponse(
                {"error": "Not authenticated"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        async with async_session_factory() as db:
            context.groups = list(
                dict.fromkeys([*context.groups, *await GroupRepository(db).group_ids_of(context.user_id)])
            )
        token = _caller.set(context)
        try:
            await self.app(scope, receive, send)
        finally:
            _caller.reset(token)


# Stateless and answering in JSON: a call is one request, with nothing to keep between two. Behind the ingress and
# the bearer token, the Host check meant for a server on a developer's machine has nothing to guard.
_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
mcp_app = CallerMiddleware(_app)


@contextlib.asynccontextmanager
async def mcp_lifespan(_app_: object):
    """Runs the server's session manager for as long as the API runs - a mounted app's own lifespan is not."""
    async with mcp.session_manager.run():
        yield
