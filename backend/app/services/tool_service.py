"""The tools the chat may call (#343): Muffin's own and those of MCP servers the users add.

Three rules everything here keeps:
- **Rights first.** The tools a person is offered are those of their own servers, of the ones shared with their groups
  or with everyone, and Muffin's own - minus what they removed for the conversation. A call is checked against the same
  list, so a tool that is not offered cannot be called by naming it.
- **A tool that changes data is never run by the agent.** The call becomes a request the person decides (`_propose`).
- **A call never raises.** The agent and the model always get a result with a code that does not change.
- **The model is given few tools, the closest to its question** (#530): Muffin's own always, and of those of MCP servers
  the closest ones when there are many. Choosing among them only narrows what is offered - never what may be called.

What the journal holds is who, which tool, how long and how it ended - never the arguments nor the answer."""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import jsonschema
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ToolSettings
from app.connectors import async_redis
from app.core.secret_store import SecretStoreError
from app.core.security.factory import RequestContext
from app.core.url_guard import UrlRefusedError, ensure_public
from app.models.conversation import Conversation
from app.models.message import MessageRole
from app.models.run import Run
from app.models.tool import (
    AUTH_BEARER,
    AUTH_NONE,
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REFUSED,
    STATUS_SUPERSEDED,
    VISIBILITY_ALL,
    VISIBILITY_GROUPS,
    ChatToolCall,
    Tool,
    ToolCallLog,
    ToolServer,
)
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.tool import (
    ToolCallRequest,
    ToolCallResult,
    ToolHitOut,
    ToolOut,
    ToolProposalOut,
    ToolServerCreate,
    ToolServerOut,
    ToolServerUpdate,
)
from app.services import vector_store
from app.services.image_generation_service import ImageGenerationError, ImageGenerationService
from app.services.secret_store_service import SecretNotFoundError, SecretStore
from app.services.tool_search_service import ToolSearchService
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


class ProposalNotFoundError(Exception):
    """There is no such request for this person."""


class NothingToDecideError(Exception):
    """No request of this turn is waiting for the person any more: decided already, superseded or expired."""


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
        # Making an image is offered to the assistant only while the function is on and open to the person (#518), and
        # retouching one only when the conversation has an image to retouch.
        images = ImageGenerationService(self.db)
        if await images.offered_to(groups):
            out.append(self._internal_out(internal_catalog.IMAGE_TOOL, removed))
            if conversation_id is not None and await images.has_images(conversation_id):
                out.append(self._internal_out(internal_catalog.IMAGE_EDIT_TOOL, removed))
        for server in await self._servers_for(user_id, groups):
            out += [self._remote_out(server, tool, removed) for tool in server.tools]
        return out

    async def definitions(
        self, user_id: str, groups: list[str], conversation_id: uuid.UUID | None, query: str | None = None
    ) -> list[ToolOut]:
        """What the model is given: the tools that can be called now, at most `TOOLS_OFFERED_MAX`. Muffin's own are
        always there. Of the tools of MCP servers, all of them while there are at most `TOOLS_SELECTED_MAX`; past that,
        the ones closest to the question (#530), so that the model is not handed - and does not pick among - dozens of
        definitions. Only the list shrinks: a call is still checked against everything the person may use."""
        usable = [tool for tool in await self.available(user_id, groups, conversation_id) if tool.available]
        fixed = [tool for tool in usable if tool.server_id is None]
        remote = [tool for tool in usable if tool.server_id is not None]
        if query and len(remote) > _settings.TOOLS_SELECTED_MAX:
            remote = await self._closest(remote, query)
        return (fixed + remote)[: _settings.TOOLS_OFFERED_MAX]

    async def _closest(self, remote: list[ToolOut], query: str) -> list[ToolOut]:
        hits = await ToolSearchService(self.db).rank(remote, query, _settings.TOOLS_SELECTED_MAX)
        # A question that says nothing about any tool ("do it") keeps the list, bounded, as it was before.
        return [hit.tool for hit in hits] or remote[: _settings.TOOLS_SELECTED_MAX]

    async def search(
        self, user: RequestContext, query: str, limit: int | None = None, conversation_id: uuid.UUID | None = None
    ) -> list[ToolHitOut]:
        """The tools the person may use, closest to the query first - by what they do, not only by their name. Only
        ranks inside what `available` gives, so a tool of a server the person cannot see is never returned, nor is its
        existence given away. Empty for an empty query: the interface lists the tools by name then."""
        candidates = await self.available(user.user_id, user.groups, conversation_id)
        hits = await ToolSearchService(self.db).rank(candidates, query, limit)
        return [ToolHitOut(**hit.tool.model_dump(), score=hit.score, match=hit.kind) for hit in hits]  # type: ignore[arg-type]

    @staticmethod
    def _internal_out(tool: internal_catalog.InternalTool, removed: set[str]) -> ToolOut:
        gone = tool.ref in removed
        return ToolOut(
            ref=tool.ref,
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            side_effect=tool.side_effect,
            available=not gone,
            reason="retiré pour cette conversation" if gone else None,
        )

    @staticmethod
    def _remote_out(server: ToolServer, tool: Tool, removed: set[str]) -> ToolOut:
        ref = str(tool.id)
        gone = ref in removed
        reason = "retiré pour cette conversation" if gone else None
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
        tool_ids = [tool.id for tool in server.tools]
        await self._forget_token(server)
        await self.db.delete(server)
        await self.db.commit()
        vector_store.delete_tool_points(tool_ids)
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
        gone_ids: list[uuid.UUID] = []
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
            gone_ids.append(gone.id)
            await self.db.delete(gone)
        server.last_synced_at = datetime.now(UTC)
        server.last_error = None
        await self.db.commit()
        await self.db.refresh(server, attribute_names=["tools", "updated_at"])
        # The index follows what was imported (#530): what is gone leaves it, what is new or changed is embedded - and a
        # tool whose text did not change is not. An index that is down never fails the synchronisation.
        vector_store.delete_tool_points(gone_ids)
        await ToolSearchService(self.db).index(
            [(tool.id, tool.name, tool.description, tool.input_schema) for tool in server.tools]
        )

    # --- the conversation's own choice ---

    async def set_disabled(self, user: RequestContext, conversation_id: uuid.UUID, refs: list[str]) -> list[str]:
        conversation = await self.db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.user_id:
            raise ToolServerNotFoundError
        conversation.disabled_tool_refs = list(dict.fromkeys(refs))
        await self.db.commit()
        return list(conversation.disabled_tool_refs)

    # --- calling ---

    async def call(self, request: ToolCallRequest, *, approved: bool = False) -> ToolCallResult:
        """One call for a person - never raises. The tool must be one the person is offered now; its arguments must
        fit its schema; the run and the person must be within their quota. The journal keeps who, which and how it
        ended.

        A tool that changes data is not run: unless the person has `approved` it, the call becomes a request that
        waits for their decision (see `_propose`)."""
        started = time.monotonic()
        result = await self._call(request, approved)
        await self._journal(request, result, int((time.monotonic() - started) * 1000))
        return result

    async def _call(self, request: ToolCallRequest, approved: bool = False) -> ToolCallResult:
        offered = {
            tool.ref: tool for tool in await self.available(request.user_id, request.groups, request.conversation_id)
        }
        tool = offered.get(request.ref)
        if tool is None:
            return self._failed("outil_indisponible", "Cet outil n'existe pas ou vous ne pouvez pas l'utiliser.")
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
        if not await self._within_quota(request, count_run=not approved):
            return self._failed("quota_depasse", "Trop d'appels d'outils : réessayez plus tard.", tool)
        if tool.side_effect and not approved:
            return await self._propose(request, tool)
        if internal_catalog.is_internal(request.ref):
            if request.ref in (internal_catalog.IMAGE_TOOL.ref, internal_catalog.IMAGE_EDIT_TOOL.ref):
                return await self._run_image(request, tool, edit=request.ref == internal_catalog.IMAGE_EDIT_TOOL.ref)
            return self._run_internal(request, tool)
        return await self._run_remote(request, tool)

    async def _run_image(self, request: ToolCallRequest, tool: ToolOut, *, edit: bool = False) -> ToolCallResult:
        """The assistant asks for an image (#518), or for one that is retouched (`edit`). The same service, rights and
        quota as the person's own request; the image goes to the run's answer. What it says to the model: that it is
        shown, and with what description."""
        if request.conversation_id is None or request.run_id is None:
            return self._failed("outil_indisponible", "Cet outil ne marche que dans une conversation.", tool)
        service = ImageGenerationService(self.db)
        sources = None
        if edit:
            run = await self.db.get(Run, request.run_id)
            sources = (
                await service.source_images(request.conversation_id, run.message_id, request.arguments.get("source"))
                if run
                else []
            )
            if not sources:
                return self._failed("aucune_image", "Il n'y a aucune image à retoucher dans cette conversation.", tool)
        try:
            image = await service.generate_for_run(
                user_id=request.user_id,
                groups=request.groups,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                prompt=str(request.arguments.get("prompt", "")),
                source_images=sources,
            )
        except ImageGenerationError as error:
            return self._failed(error.code, error.message, tool)
        except Exception:
            logger.exception("The image asked for by the assistant could not be made")
            return self._failed("erreur_outil", "L'image n'a pas pu être générée.", tool)
        made = "retouchée" if edit else "générée"
        return ToolCallResult(
            ok=True,
            code="ok",
            text=(
                f"Image {made} par IA et affichée à l'utilisateur sous ta réponse. "
                f"Description envoyée au fournisseur{' avec l’image' if edit else ''} : "
                f"« {(image.prompt or '')[:500]} ». "
                "Ne mets aucun lien ni aucune image dans ta réponse : dis simplement ce qui a été fait."
            ),
            tool_name=tool.name,
        )

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

    async def _within_quota(self, request: ToolCallRequest, *, count_run: bool = True) -> bool:
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
            if request.run_id is not None and count_run:
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

    # --- the requests the person decides ---

    async def _propose(self, request: ToolCallRequest, tool: ToolOut) -> ToolCallResult:
        """A tool that changes data is not run: the call becomes a request that stays in the discussion, with the
        arguments the person would agree to. Nothing is waiting - no task, no connection: the person decides when they
        like, and the decision runs the tool (`decide`)."""
        if request.conversation_id is None:
            return self._failed("outil_indisponible", "Cet outil ne peut être proposé que dans une conversation.", tool)
        waiting = (
            await self.db.execute(
                select(ChatToolCall.id).where(
                    ChatToolCall.user_id == request.user_id, ChatToolCall.status == STATUS_PENDING
                )
            )
        ).all()
        if len(waiting) >= _settings.TOOLS_PENDING_PER_USER:
            return self._failed("quota_depasse", "Trop de demandes en attente : décidez-en avant d'en faire.", tool)
        proposal = ChatToolCall(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            tool_ref=request.ref[:160],
            tool_name=tool.name,
            server_name=tool.server_name,
            arguments=request.arguments,
        )
        self.db.add(proposal)
        await self.db.flush()
        await self.db.commit()
        return ToolCallResult(
            ok=False,
            code="confirmation_demandee",
            text="Cet outil modifie des données : une demande d'autorisation a été présentée à l'utilisateur. "
            "Rien n'a été exécuté.",
            tool_name=tool.name,
            server_name=tool.server_name,
            proposal_id=proposal.id,
            arguments=request.arguments,
        )

    async def proposals_for_conversation(self, conversation_id: uuid.UUID, user_id: str) -> list[ToolProposalOut]:
        rows = (
            (
                await self.db.execute(
                    select(ChatToolCall)
                    .where(ChatToolCall.conversation_id == conversation_id, ChatToolCall.user_id == user_id)
                    .order_by(ChatToolCall.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [self._proposal_out(row) for row in rows]

    async def proposals_for_run(self, run_id: uuid.UUID, user_id: str) -> list[ToolProposalOut]:
        rows = (
            (
                await self.db.execute(
                    select(ChatToolCall)
                    .where(ChatToolCall.run_id == run_id, ChatToolCall.user_id == user_id)
                    .order_by(ChatToolCall.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [self._proposal_out(row) for row in rows]

    async def supersede_pending(self, conversation_id: uuid.UUID) -> None:
        """The person wrote something else instead of deciding: what was waiting is abandoned and can no longer be
        authorised - an old request must not be run on a click made for another question."""
        await self.db.execute(
            update(ChatToolCall)
            .where(ChatToolCall.conversation_id == conversation_id, ChatToolCall.status == STATUS_PENDING)
            .values(status=STATUS_SUPERSEDED)
        )

    async def decide(self, user: RequestContext, run_id: uuid.UUID, approve: bool) -> list[ToolProposalOut]:
        """The person's answer for the requests of one turn: all authorised, or all refused.

        Each request is claimed with a conditional update, so a second click - or a second tab - finds nothing to decide
        and runs nothing twice. What is authorised is run **with the rights the person has now**: a tool removed, a
        server switched off or no longer shared since is not run, and is reported as failed. The outcome is written into
        the conversation, where the next turn reads it."""
        now = datetime.now(UTC)
        mine = (ChatToolCall.run_id == run_id) & (ChatToolCall.user_id == user.user_id)
        await self.db.execute(
            update(ChatToolCall)
            .where(mine, ChatToolCall.status == STATUS_PENDING)
            .where(ChatToolCall.created_at <= now - timedelta(hours=_settings.TOOLS_PENDING_HOURS))
            .values(status=STATUS_EXPIRED)
        )
        claimed = (
            (
                await self.db.execute(
                    update(ChatToolCall)
                    .where(mine, ChatToolCall.status == STATUS_PENDING)
                    .values(status=STATUS_APPROVED if approve else STATUS_REFUSED, decided_at=now)
                    .returning(ChatToolCall.id)
                )
            )
            .scalars()
            .all()
        )
        await self.db.commit()
        if not claimed:
            raise (
                NothingToDecideError if await self.proposals_for_run(run_id, user.user_id) else ProposalNotFoundError
            )
        rows = (
            (
                await self.db.execute(
                    select(ChatToolCall).where(ChatToolCall.id.in_(claimed)).order_by(ChatToolCall.created_at)
                )
            )
            .scalars()
            .all()
        )
        lines = []
        for row in rows:
            if not approve:
                lines.append(
                    f"Vous avez refusé l'outil « {row.tool_name} »{_where(row.server_name)} : rien n'a été exécuté."
                )
                continue
            result = await self.call(
                ToolCallRequest(
                    user_id=user.user_id,
                    groups=user.groups,
                    conversation_id=row.conversation_id,
                    run_id=row.run_id,
                    ref=row.tool_ref,
                    arguments=row.arguments,
                ),
                approved=True,
            )
            row.status = STATUS_EXECUTED if result.ok else STATUS_FAILED
            row.result_code = result.code
            lines.append(_outcome_line(row, result))
        await ConversationRepository(self.db).add_message(
            rows[0].conversation_id, MessageRole.ASSISTANT, "\n\n".join(lines)
        )
        await self.db.commit()
        verdict = "authorised" if approve else "refused"
        logger.info(f"{len(rows)} tool request(s) of run {run_id} {verdict} by {user.user_id}")
        return [self._proposal_out(row) for row in rows]

    @staticmethod
    def _proposal_out(row: ChatToolCall) -> ToolProposalOut:
        return ToolProposalOut(
            id=row.id,
            run_id=row.run_id,
            conversation_id=row.conversation_id,
            tool_name=row.tool_name,
            server_name=row.server_name,
            arguments=row.arguments,
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
            decided_at=row.decided_at,
            result_code=row.result_code,
        )

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


def _where(server_name: str | None) -> str:
    return f" (serveur {server_name})" if server_name else ""


def _outcome_line(row: ChatToolCall, result: ToolCallResult) -> str:
    """What the discussion says of a tool the person authorised. What the server answered is data from a third party: it
    goes in a code block, which the chat shows as text and never as markup, with any fence of its own made harmless."""
    if result.ok:
        body = result.text.replace("```", "'''")
        cut = "\n[résultat tronqué]" if result.truncated else ""
        return (
            f"L'outil « {row.tool_name} »{_where(row.server_name)} a été exécuté avec votre accord :"
            f"\n\n```\n{body}{cut}\n```"
        )
    return (
        f"L'outil « {row.tool_name} »{_where(row.server_name)} n'a pas pu être exécuté ({result.code}) : {result.text}"
    )
