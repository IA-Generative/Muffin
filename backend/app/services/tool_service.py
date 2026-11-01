"""The tools the chat may call (#343): Muffin's own and those of MCP servers the users add.

Three rules everything here keeps:
- **Rights first.** The tools a person is offered are those of their own servers, of the ones shared with their groups
  or with everyone, and Muffin's own - minus what they removed for the conversation. A call is checked against the same
  list, so a tool that is not offered cannot be called by naming it.
- **A tool that changes data is never called** - not until it can be approved by the person (not built yet).
- **A call never raises.** The agent and the model always get a result with a code that does not change.

What the journal holds is who, which tool, how long and how it ended - never the arguments nor the answer."""

import json
import time
import uuid
from datetime import UTC, datetime

import jsonschema
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ToolSettings
from app.connectors import async_redis
from app.core.secret_store import SecretStoreError
from app.core.security.factory import RequestContext
from app.core.url_guard import UrlRefusedError, ensure_public
from app.models.conversation import Conversation
from app.models.tool import AUTH_BEARER, AUTH_NONE, VISIBILITY_ALL, VISIBILITY_GROUPS, Tool, ToolCallLog, ToolServer
from app.schemas.tool import (
    ToolCallRequest,
    ToolCallResult,
    ToolOut,
    ToolServerCreate,
    ToolServerOut,
    ToolServerUpdate,
)
from app.services.secret_store_service import SecretNotFoundError, SecretStore
from app.services.tools import internal_catalog, mcp_client
from app.services.tools.mcp_client import ToolServerError

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ToolSettings()

_PURPOSE = "tool-server-token"
_ARGUMENTS_MAX_CHARS = 8000


class ToolServerNotFoundError(Exception):
    pass


class ToolServerNotOwnedError(Exception):
    pass


class TooManyToolServersError(Exception):
    pass


class InvalidToolServerError(Exception):
    """What was asked for a server cannot be: the message says why, for the person."""


class ToolService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- who may use what ---

    @staticmethod
    def _usable_by(server: ToolServer, user_id: str, groups: list[str]) -> bool:
        if not server.enabled:
            return False
        if server.owner_id == user_id or server.visibility == VISIBILITY_ALL:
            return True
        return server.visibility == VISIBILITY_GROUPS and bool(set(server.group_ids) & set(groups))

    async def _servers_for(self, user_id: str, groups: list[str]) -> list[ToolServer]:
        rows = (await self.db.execute(select(ToolServer).order_by(ToolServer.name))).scalars().all()
        return [server for server in rows if self._usable_by(server, user_id, groups)]

    async def _disabled_refs(self, conversation_id: uuid.UUID | None, user_id: str) -> set[str]:
        if conversation_id is None:
            return set()
        conversation = await self.db.get(Conversation, conversation_id)
        # Someone else's conversation removes nothing for this person.
        return set(conversation.disabled_tool_refs) if conversation and conversation.user_id == user_id else set()

    async def available(self, user_id: str, groups: list[str], conversation_id: uuid.UUID | None) -> list[ToolOut]:
        """Every tool the person may use, with what keeps one from being called now: removed for this conversation, or
        changing data. Muffin's own first."""
        removed = await self._disabled_refs(conversation_id, user_id)
        out = [self._internal_out(tool, removed) for tool in internal_catalog.INTERNAL_TOOLS if tool.implemented]
        for server in await self._servers_for(user_id, groups):
            out += [self._remote_out(server, tool, removed) for tool in server.tools]
        return out

    async def definitions(self, user_id: str, groups: list[str], conversation_id: uuid.UUID | None) -> list[ToolOut]:
        """What the model is given: the tools that can be called now, at most `TOOLS_OFFERED_MAX`."""
        usable = [tool for tool in await self.available(user_id, groups, conversation_id) if tool.available]
        return usable[: _settings.TOOLS_OFFERED_MAX]

    @staticmethod
    def _internal_out(tool: internal_catalog.InternalTool, removed: set[str]) -> ToolOut:
        gone = tool.ref in removed
        return ToolOut(
            ref=tool.ref,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            side_effect=tool.side_effect,
            available=not gone and not tool.side_effect,
            reason="retiré pour cette conversation" if gone else None,
        )

    @staticmethod
    def _remote_out(server: ToolServer, tool: Tool, removed: set[str]) -> ToolOut:
        ref = str(tool.id)
        gone = ref in removed
        reason = (
            "retiré pour cette conversation"
            if gone
            else "modifie des données : il ne sera appelable qu'avec votre accord, pas encore disponible"
            if tool.side_effect
            else None
        )
        return ToolOut(
            ref=ref,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            server_id=server.id,
            server_name=server.name,
            side_effect=tool.side_effect,
            available=reason is None,
            reason=reason,
        )

    # --- servers ---

    async def list_servers(self, user: RequestContext) -> list[ToolServerOut]:
        servers = await self._servers_for(user.user_id, user.groups)
        # A person's own servers also when switched off: they have to be able to switch them back on.
        mine = (await self.db.execute(select(ToolServer).where(ToolServer.owner_id == user.user_id))).scalars().all()
        seen = {server.id for server in servers}
        servers += [server for server in mine if server.id not in seen]
        return [self._server_out(server, user) for server in sorted(servers, key=lambda s: s.name.lower())]

    async def get_server(self, user: RequestContext, server_id: uuid.UUID) -> ToolServerOut:
        server = await self._get_visible(user, server_id)
        return self._server_out(server, user)

    async def create_server(self, user: RequestContext, body: ToolServerCreate) -> ToolServerOut:
        owned = (await self.db.execute(select(ToolServer).where(ToolServer.owner_id == user.user_id))).scalars().all()
        if len(owned) >= _settings.TOOL_SERVERS_PER_USER:
            raise TooManyToolServersError
        url = await self._checked_url(body.url)
        self._check_sharing(user, body.visibility, body.group_ids)
        if body.auth_mode == AUTH_BEARER and not body.token:
            raise InvalidToolServerError("Ce serveur demande un jeton.")
        server = ToolServer(
            owner_id=user.user_id,
            name=body.name,
            url=url,
            auth_mode=body.auth_mode,
            visibility=body.visibility,
            group_ids=list(dict.fromkeys(body.group_ids)) if body.visibility == VISIBILITY_GROUPS else [],
        )
        self.db.add(server)
        await self.db.flush()
        if body.auth_mode == AUTH_BEARER and body.token:
            server.secret_id = (
                await SecretStore(self.db).put(
                    owner=user.user_id, purpose=_PURPOSE, plaintext=body.token, created_by=user.user_id
                )
            ).id
        await self.db.commit()
        logger.info(f"Tool server {server.id} ({server.name!r}) added by {user.user_id}")
        await self._sync(server)
        return self._server_out(server, user)

    async def update_server(self, user: RequestContext, server_id: uuid.UUID, body: ToolServerUpdate) -> ToolServerOut:
        server = await self._get_owned(user, server_id)
        changes = body.model_dump(exclude_unset=True, exclude={"token"})
        if "url" in changes and changes["url"] is not None:
            changes["url"] = await self._checked_url(changes["url"])
        visibility = changes.get("visibility", server.visibility)
        group_ids = changes.get("group_ids", server.group_ids) or []
        if "visibility" in changes or "group_ids" in changes:
            self._check_sharing(user, visibility, group_ids)
            changes["group_ids"] = list(dict.fromkeys(group_ids)) if visibility == VISIBILITY_GROUPS else []
        for key, value in changes.items():
            if value is not None:
                setattr(server, key, value)
        auth_mode = server.auth_mode
        if auth_mode == AUTH_NONE and server.secret_id is not None:
            await self._forget_token(server)
        elif body.token:
            await self._set_token(server, user, body.token)
        elif auth_mode == AUTH_BEARER and server.secret_id is None:
            raise InvalidToolServerError("Ce serveur demande un jeton.")
        await self.db.commit()
        logger.info(f"Tool server {server.id} changed by {user.user_id}: {', '.join(sorted(changes))}")
        if "url" in changes or body.token:
            await self._sync(server)
        return self._server_out(server, user)

    async def delete_server(self, user: RequestContext, server_id: uuid.UUID) -> None:
        server = await self._get_owned(user, server_id)
        await self._forget_token(server)
        await self.db.delete(server)
        await self.db.commit()
        logger.info(f"Tool server {server_id} deleted by {user.user_id}")

    async def sync_server(self, user: RequestContext, server_id: uuid.UUID) -> ToolServerOut:
        server = await self._get_owned(user, server_id)
        await self._sync(server)
        return self._server_out(server, user)

    async def _sync(self, server: ToolServer) -> None:
        """Takes the tools of the server again (`tools/list`). A server that does not answer keeps the tools it had and
        says why."""
        await self.db.refresh(server, attribute_names=["tools"])
        try:
            remote = await mcp_client.list_tools(server.url, await self._token(server))
        except ToolServerError as error:
            server.last_error = error.message[:300]
            await self.db.commit()
            return
        known = {tool.name: tool for tool in server.tools}
        for item in remote:
            tool = known.pop(item.name, None)
            if tool is None:
                self.db.add(
                    Tool(
                        server_id=server.id,
                        name=item.name,
                        description=item.description,
                        input_schema=item.input_schema,
                        side_effect=item.side_effect,
                    )
                )
            else:
                tool.description, tool.input_schema, tool.side_effect = (
                    item.description,
                    item.input_schema,
                    item.side_effect,
                )
        for gone in known.values():
            await self.db.delete(gone)
        server.last_synced_at = datetime.now(UTC)
        server.last_error = None
        await self.db.commit()
        await self.db.refresh(server, attribute_names=["tools", "updated_at"])

    # --- the conversation's own choice ---

    async def set_disabled(self, user: RequestContext, conversation_id: uuid.UUID, refs: list[str]) -> list[str]:
        conversation = await self.db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ToolServerNotFoundError
        conversation.disabled_tool_refs = list(dict.fromkeys(refs))
        await self.db.commit()
        return list(conversation.disabled_tool_refs)

    # --- calling ---

    async def call(self, request: ToolCallRequest) -> ToolCallResult:
        """One call for a person - never raises. The tool must be one the person is offered now; its arguments must
        fit its schema; the run and the person must be within their quota. The journal keeps who, which and how it
        ended."""
        started = time.monotonic()
        result = await self._call(request)
        await self._journal(request, result, int((time.monotonic() - started) * 1000))
        return result

    async def _call(self, request: ToolCallRequest) -> ToolCallResult:
        offered = {
            tool.ref: tool for tool in await self.available(request.user_id, request.groups, request.conversation_id)
        }
        tool = offered.get(request.ref)
        if tool is None:
            return self._failed("outil_indisponible", "Cet outil n'existe pas ou vous ne pouvez pas l'utiliser.")
        if tool.side_effect:
            return self._failed(
                "confirmation_requise",
                "Cet outil modifie des données : il n'est pas appelable sans votre accord.",
                tool,
            )
        if not tool.available:
            return self._failed("outil_indisponible", "Cet outil est retiré pour cette conversation.", tool)
        if len(json.dumps(request.arguments, default=str)) > _ARGUMENTS_MAX_CHARS:
            return self._failed("arguments_invalides", "Les arguments sont trop longs.", tool)
        try:
            jsonschema.validate(request.arguments, tool.input_schema)
        except jsonschema.ValidationError as error:
            return self._failed("arguments_invalides", f"Arguments invalides : {error.message[:200]}", tool)
        except jsonschema.SchemaError:
            pass  # a schema this server wrote badly: its own checks then decide
        if not await self._within_quota(request):
            return self._failed("quota_depasse", "Trop d'appels d'outils : réessayez plus tard.", tool)
        if internal_catalog.is_internal(request.ref):
            return self._run_internal(request, tool)
        return await self._run_remote(request, tool)

    def _run_internal(self, request: ToolCallRequest, tool: ToolOut) -> ToolCallResult:
        internal = internal_catalog.find(request.ref)
        if internal is None:
            return self._failed("outil_indisponible", "Cet outil n'existe pas.", tool)
        try:
            text = internal.run(request.arguments)
        except internal_catalog.ToolArgumentError as error:
            return self._failed("arguments_invalides", str(error), tool)
        except Exception:
            logger.exception(f"The internal tool {internal.id} failed")
            return self._failed("erreur_outil", "L'outil a échoué.", tool)
        return ToolCallResult(ok=True, code="ok", text=text[: _settings.TOOLS_OUTPUT_MAX_CHARS], tool_name=tool.name)

    @staticmethod
    def _failed(code: str, message: str, tool: ToolOut | None = None) -> ToolCallResult:
        return ToolCallResult(
            ok=False,
            code=code,
            text=message,
            tool_name=tool.name if tool else "",
            server_name=tool.server_name if tool else None,
        )

    async def _within_quota(self, request: ToolCallRequest) -> bool:
        """Counters in Redis, one per run and one per person per minute. If Redis cannot be reached the call goes on:
        a quota is a protection, not a reason for the chat to break."""
        try:
            redis = async_redis()
            checks = [
                (
                    f"tools:user:{request.user_id}:{int(time.time() // 60)}",
                    90,
                    _settings.TOOLS_CALLS_PER_USER_PER_MINUTE,
                )
            ]
            if request.run_id is not None:
                checks.append((f"tools:run:{request.run_id}", 3600, _settings.TOOLS_CALLS_PER_RUN))
            for key, ttl, limit in checks:
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, ttl)
                if count > limit:
                    return False
        except Exception:
            logger.warning("The tool quota could not be checked", exc_info=True)
        return True

    async def _journal(self, request: ToolCallRequest, result: ToolCallResult, duration_ms: int) -> None:
        try:
            server_id = None
            if not internal_catalog.is_internal(request.ref):
                try:
                    tool = await self.db.get(Tool, uuid.UUID(request.ref))
                    server_id = tool.server_id if tool else None
                except ValueError:
                    pass
            self.db.add(
                ToolCallLog(
                    user_id=request.user_id,
                    run_id=request.run_id,
                    tool_ref=request.ref[:160],
                    server_id=server_id,
                    outcome=result.code,
                    duration_ms=duration_ms,
                )
            )
            await self.db.commit()
        except Exception:
            logger.warning("A tool call could not be journalised", exc_info=True)
            await self.db.rollback()

    # --- internals ---

    async def _run_remote(self, request: ToolCallRequest, tool: ToolOut) -> ToolCallResult:
        record = await self.db.get(Tool, uuid.UUID(request.ref))
        server = await self.db.get(ToolServer, tool.server_id) if tool.server_id else None
        if record is None or server is None:
            return self._failed("outil_indisponible", "Cet outil n'existe plus.", tool)
        try:
            # The address is checked again here, at each call: see app/core/url_guard.py.
            result = await mcp_client.call_tool(server.url, await self._token(server), record.name, request.arguments)
        except ToolServerError as error:
            return self._failed(error.code, error.message, tool)
        if result.is_error:
            # What the server says of its own failure is data from a third party, bounded like any answer of it.
            return self._failed("erreur_outil", result.text or "L'outil a répondu par une erreur.", tool)
        return ToolCallResult(
            ok=True,
            code="ok",
            text=result.text,
            truncated=result.truncated,
            tool_name=tool.name,
            server_name=server.name,
        )

    async def _checked_url(self, url: str) -> str:
        try:
            return await ensure_public(url)
        except UrlRefusedError as error:
            raise InvalidToolServerError(str(error)) from error

    @staticmethod
    def _check_sharing(user: RequestContext, visibility: str, group_ids: list[str]) -> None:
        if visibility == VISIBILITY_GROUPS:
            if not group_ids:
                raise InvalidToolServerError("Choisissez au moins un groupe.")
            outside = [group for group in group_ids if group not in user.groups]
            if outside:
                raise InvalidToolServerError("Vous ne pouvez partager qu'avec les groupes dont vous faites partie.")

    async def _get_visible(self, user: RequestContext, server_id: uuid.UUID) -> ToolServer:
        server = await self.db.get(ToolServer, server_id)
        if server is None or not (
            server.owner_id == user.user_id or self._usable_by(server, user.user_id, user.groups)
        ):
            raise ToolServerNotFoundError
        return server

    async def _get_owned(self, user: RequestContext, server_id: uuid.UUID) -> ToolServer:
        server = await self._get_visible(user, server_id)
        if server.owner_id != user.user_id:
            raise ToolServerNotOwnedError
        return server

    async def _token(self, server: ToolServer) -> str | None:
        if server.auth_mode != AUTH_BEARER or server.secret_id is None:
            return None
        try:
            return await SecretStore(self.db).reveal(server.secret_id, owner=server.owner_id, purpose=_PURPOSE)
        except (SecretNotFoundError, SecretStoreError):
            logger.warning(f"The token of tool server {server.id} could not be read")
            return None

    async def _set_token(self, server: ToolServer, user: RequestContext, token: str) -> None:
        store = SecretStore(self.db)
        if server.secret_id is None:
            server.secret_id = (
                await store.put(owner=user.user_id, purpose=_PURPOSE, plaintext=token, created_by=user.user_id)
            ).id
        else:
            await store.replace(server.secret_id, token, owner=server.owner_id, purpose=_PURPOSE)

    async def _forget_token(self, server: ToolServer) -> None:
        if server.secret_id is not None:
            try:
                await SecretStore(self.db).delete(server.secret_id, owner=server.owner_id, purpose=_PURPOSE)
            except SecretNotFoundError:
                pass
            server.secret_id = None

    def _server_out(self, server: ToolServer, user: RequestContext) -> ToolServerOut:
        owner = server.owner_id == user.user_id
        return ToolServerOut(
            id=server.id,
            name=server.name,
            url=server.url if owner else _origin(server.url),
            auth_mode=server.auth_mode,  # type: ignore[arg-type]
            has_token=server.secret_id is not None,
            visibility=server.visibility,  # type: ignore[arg-type]
            group_ids=list(server.group_ids) if owner else [],
            enabled=server.enabled,
            is_owner=owner,
            last_synced_at=server.last_synced_at,
            last_error=server.last_error if owner else None,
            tools=[self._remote_out(server, tool, set()) for tool in sorted(server.tools, key=lambda t: t.name)],
        )


def _origin(url: str) -> str:
    """What a person a server is shared with is shown of its address: where it is, not the path or the query, which may
    hold a key."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}"
