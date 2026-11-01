"""The assistants (#514): named settings for the chat, shared the way collections are.

The rule everything here keeps: an assistant *designates* collections and never grants access to them. What a chat with
it searches is what it designates **and** the person using it may read (`resolve`) - worked out here in code, not left
to a model. Whoever receives an assistant learns nothing of a collection they cannot read: not its name, only that there
is one more they cannot see."""

import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AssistantSettings
from app.core.security.factory import RequestContext
from app.core.sharing import hash_identifier, mask_email, mask_group, normalize_email, normalize_group
from app.models.assistant import Assistant
from app.models.collection import CollectionVisibility, ShareSubjectType
from app.repositories.assistant_repository import AssistantRepository
from app.repositories.collection_repository import CollectionRepository
from app.schemas.assistant import (
    AssistantCollectionOut,
    AssistantCreate,
    AssistantHitOut,
    AssistantOut,
    AssistantRefOut,
    AssistantUpdate,
)
from app.schemas.collection import ShareCreate, ShareOut, ShareUpdate
from app.services.assistant_search_service import AssistantSearchService, forget
from app.services.collection_service import AlreadyInvitedError, ShareNotFoundError
from app.services.group_service import GroupService

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = AssistantSettings()


class AssistantNotFoundError(Exception):
    """It does not exist, or the caller may not read it - the two look the same."""


class AssistantNotEditableError(Exception):
    pass


class AssistantNotOwnedError(Exception):
    """Sharing, publishing and deleting stay with the author (or an administrator, for a public one)."""


class PublicNotAllowedError(Exception):
    pass


class TooManyAssistantsError(Exception):
    pass


class NoReadableCollectionError(Exception):
    """The assistant designates collections and the caller may read none of them: searching everything instead would
    answer from sources it was not meant to use."""


@dataclass(frozen=True)
class ResolvedAssistant:
    """What a run takes from an assistant: its collections that the caller may read, and the rest as it was then."""

    id: uuid.UUID
    name: str
    version: int
    instructions: str
    collection_ids: list[uuid.UUID]
    inaccessible_collection_count: int
    include_descendants: bool
    web_search_allowed: bool
    disabled_tools: list[str]
    # The assistants this one may consult for the question (#531):
    # [{id, name, description, collection_ids, disabled_tools}].
    consultable: list[dict]


class AssistantService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.assistants = AssistantRepository(db)
        self.collections = CollectionRepository(db)

    # --- reading ---

    async def list_assistants(self, user: RequestContext) -> list[AssistantOut]:
        rows = await self.assistants.list_accessible(user.user_id, user.groups)
        counts = await self.assistants.share_counts(
            [assistant.id for assistant, _ in rows if self._owns(assistant, user)]
        )
        readable = await self._readable_collections(
            user, {uuid.UUID(cid) for assistant, _ in rows for cid in assistant.collection_ids}
        )
        # Every assistant the caller may read is in `rows`: that is who they may be shown as consulting.
        known = {assistant.id: assistant.name for assistant, _ in rows}
        return [
            self._present(assistant, user, writable, readable, counts.get(assistant.id, 0), known)
            for assistant, writable in rows
        ]

    async def get(self, assistant_id: uuid.UUID, user: RequestContext) -> AssistantOut:
        assistant, writable = await self._get_readable(assistant_id, user)
        readable = await self._readable_collections(user, {uuid.UUID(cid) for cid in assistant.collection_ids})
        counts = await self.assistants.share_counts([assistant.id]) if self._owns(assistant, user) else {}
        return self._present(
            assistant, user, writable, readable, counts.get(assistant.id, 0), await self._known_names(user)
        )

    # --- writing ---

    async def create(self, user: RequestContext, body: AssistantCreate) -> AssistantOut:
        owned = [a for a, _ in await self.assistants.list_accessible(user.user_id, []) if a.owner_id == user.user_id]
        if len(owned) >= _settings.ASSISTANTS_PER_USER:
            raise TooManyAssistantsError
        # What is designated must be readable by its author: nobody designates a collection they cannot see.
        designated = await self._readable_collections(user, set(body.collection_ids))
        assistant = await self.assistants.create(
            user.user_id,
            name=body.name,
            description=body.description.strip(),
            icon=body.icon,
            color=body.color,
            instructions=body.instructions.strip(),
            hide_instructions=body.hide_instructions,
            collection_ids=[str(cid) for cid in dict.fromkeys(body.collection_ids) if cid in designated],
            include_descendants=body.include_descendants,
            web_search_allowed=body.web_search_allowed,
            disabled_tools=body.disabled_tools,
            consult_mode=body.consult_mode,
            consult_assistant_ids=await self._designated_assistants(user, body.consult_assistant_ids, set()),
            suggestions=body.suggestions,
        )
        await self.db.commit()
        await self.db.refresh(assistant)
        # Its description is embedded as it is written, so that it is found from the first search.
        await AssistantSearchService(self.db).index(assistant)
        logger.info(f"Assistant {assistant.id} ({assistant.name!r}) created by {user.user_id}")
        return await self.get(assistant.id, user)

    async def update(self, assistant_id: uuid.UUID, user: RequestContext, body: AssistantUpdate) -> AssistantOut:
        assistant, writable = await self._get_readable(assistant_id, user)
        if not (writable or self._admin_over(assistant, user)):
            raise AssistantNotEditableError
        changes = {
            key: value.strip() if key in ("description", "instructions") else value
            for key, value in body.model_dump(
                exclude_unset=True, exclude={"collection_ids", "consult_assistant_ids"}
            ).items()
            if value is not None
        }
        if body.collection_ids is not None:
            # The editor changes the collections they can see. Those they cannot see stay as they are: saving must not
            # silently drop what the author designated and the editor was never shown.
            requested = list(dict.fromkeys(body.collection_ids))
            seen_by_editor = await self._readable_collections(
                user, {uuid.UUID(cid) for cid in assistant.collection_ids}
            )
            now_readable = await self._readable_collections(user, set(requested))
            kept_hidden = [cid for cid in assistant.collection_ids if uuid.UUID(cid) not in seen_by_editor]
            changes["collection_ids"] = [str(cid) for cid in requested if cid in now_readable] + kept_hidden
        if body.consult_assistant_ids is not None:
            # Same as the collections: what the editor is not shown stays as it is.
            shown = await self._known_names(user)
            kept_hidden = [aid for aid in assistant.consult_assistant_ids if uuid.UUID(aid) not in shown]
            changes["consult_assistant_ids"] = (
                await self._designated_assistants(user, body.consult_assistant_ids, {assistant.id}) + kept_hidden
            )
        changed = {key: value for key, value in changes.items() if getattr(assistant, key) != value}
        if changed:
            for key, value in changed.items():
                setattr(assistant, key, value)
            assistant.version += 1
            await self.db.commit()
            await self.db.refresh(assistant)
            # What an assistant says of itself changed: its point is made again (the hash tells nothing else did).
            if changed.keys() & {"name", "description", "suggestions"}:
                await AssistantSearchService(self.db).index(assistant)
            # Which fields, never what the instructions say: they can be long, and are not for the log.
            logger.info(
                f"Assistant {assistant.id} changed by {user.user_id} to version {assistant.version}: "
                f"{', '.join(sorted(changed))}"
            )
        return await self.get(assistant_id, user)

    async def delete(self, assistant_id: uuid.UUID, user: RequestContext) -> None:
        assistant, _ = await self._get_readable(assistant_id, user)
        if not (self._owns(assistant, user) or self._admin_over(assistant, user)):
            raise AssistantNotOwnedError
        await self.assistants.delete(assistant)
        await self.db.commit()
        forget(assistant_id)
        logger.info(f"Assistant {assistant_id} deleted by {user.user_id}")

    async def duplicate(self, assistant_id: uuid.UUID, user: RequestContext) -> AssistantOut:
        """ "My version" of an assistant: private, the caller's. It takes the collections the caller reads, and the
        instructions only if the caller is allowed to see them - a copy never gets out what was hidden."""
        assistant, writable = await self._get_readable(assistant_id, user)
        sees_instructions = writable or self._owns(assistant, user) or not assistant.hide_instructions
        readable = await self._readable_collections(user, {uuid.UUID(cid) for cid in assistant.collection_ids})
        copy = await self.create(
            user,
            AssistantCreate(
                name=f"{assistant.name} (copie)"[:100],
                description=assistant.description,
                icon=assistant.icon,
                color=assistant.color,
                instructions=assistant.instructions if sees_instructions else "",
                collection_ids=[uuid.UUID(cid) for cid in assistant.collection_ids if uuid.UUID(cid) in readable],
                include_descendants=assistant.include_descendants,
                web_search_allowed=assistant.web_search_allowed,
                disabled_tools=list(assistant.disabled_tools),
                consult_mode=assistant.consult_mode,
                consult_assistant_ids=[uuid.UUID(aid) for aid in assistant.consult_assistant_ids],
                suggestions=list(assistant.suggestions),
            ),
        )
        logger.info(f"Assistant {assistant_id} duplicated by {user.user_id} as {copy.id}")
        return copy

    async def set_visibility(
        self, assistant_id: uuid.UUID, user: RequestContext, visibility: CollectionVisibility
    ) -> AssistantOut:
        assistant, _ = await self._get_readable(assistant_id, user)
        if not (self._owns(assistant, user) or self._admin_over(assistant, user)):
            raise AssistantNotOwnedError
        if visibility == CollectionVisibility.PUBLIC and not user.is_admin and not _settings.ASSISTANTS_PUBLIC_ENABLED:
            raise PublicNotAllowedError
        if assistant.visibility != visibility:
            assistant.visibility = visibility
            assistant.version += 1
            await self.db.commit()
            await self.db.refresh(assistant)
            logger.info(f"Assistant {assistant.id} made {visibility.value} by {user.user_id}")
        return await self.get(assistant_id, user)

    # --- sharing ---

    async def create_share(self, assistant_id: uuid.UUID, user: RequestContext, create: ShareCreate) -> ShareOut:
        """Like a collection's: the identifier is never looked up, only its hash is kept until that person logs in."""
        assistant = await self._get_owned(assistant_id, user)
        try:
            if create.group_id is not None:
                group = await GroupService(self.db).get_visible(create.group_id, user)
                share = await self.assistants.create_active_group_share(
                    assistant.id, group.id, group.name, create.permission
                )
            else:
                if create.subject_type == ShareSubjectType.USER:
                    normalized = normalize_email(create.identifier)
                    hint = mask_email(normalized)
                else:
                    normalized = normalize_group(create.identifier)
                    hint = mask_group(normalized)
                share = await self.assistants.create_share(
                    assistant.id, create.subject_type, hash_identifier(normalized), hint, create.permission
                )
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()
            raise AlreadyInvitedError(str(assistant_id)) from error
        logger.info(
            f"Assistant {assistant.id} shared by {user.user_id} ({create.subject_type.value}, {create.permission})"
        )
        return ShareOut.from_model(share)

    async def list_shares(self, assistant_id: uuid.UUID, user: RequestContext) -> list[ShareOut]:
        await self._get_owned(assistant_id, user)
        return [ShareOut.from_model(share) for share in await self.assistants.list_shares(assistant_id)]

    async def update_share(
        self, assistant_id: uuid.UUID, user: RequestContext, share_id: uuid.UUID, update: ShareUpdate
    ) -> ShareOut:
        await self._get_owned(assistant_id, user)
        share = await self.assistants.get_share(assistant_id, share_id)
        if share is None:
            raise ShareNotFoundError(str(share_id))
        share.permission = update.permission
        await self.db.commit()
        logger.info(f"Share {share_id} of assistant {assistant_id} set to {update.permission} by {user.user_id}")
        return ShareOut.from_model(share)

    async def delete_share(self, assistant_id: uuid.UUID, user: RequestContext, share_id: uuid.UUID) -> None:
        await self._get_owned(assistant_id, user)
        share = await self.assistants.get_share(assistant_id, share_id)
        if share is None:
            raise ShareNotFoundError(str(share_id))
        await self.assistants.delete_share(share)
        await self.db.commit()
        logger.info(f"Share {share_id} of assistant {assistant_id} removed by {user.user_id}")

    # --- using ---

    async def resolve(self, user: RequestContext, assistant_id: uuid.UUID, question: str = "") -> ResolvedAssistant:
        """What a chat with this assistant uses, independent of any route (the OpenAI-compatible API and the MCP server
        reuse it). The collections are those the assistant designates that **this** user may read; the assistants it may
        consult for `question` are worked out here too, in code (see `_consultable`)."""
        assistant, _ = await self._get_readable(assistant_id, user)
        designated = [uuid.UUID(cid) for cid in assistant.collection_ids]
        readable = await self._readable_collections(user, set(designated))
        usable = [cid for cid in designated if cid in readable]
        if designated and not usable:
            raise NoReadableCollectionError(str(assistant_id))
        return ResolvedAssistant(
            id=assistant.id,
            name=assistant.name,
            version=assistant.version,
            instructions=assistant.instructions,
            collection_ids=usable,
            inaccessible_collection_count=len(designated) - len(usable),
            include_descendants=assistant.include_descendants,
            web_search_allowed=assistant.web_search_allowed,
            disabled_tools=list(assistant.disabled_tools),
            consultable=await self._consultable(user, assistant, question),
        )

    # --- searching ---

    async def search(self, user: RequestContext, query: str, limit: int | None = None) -> list[AssistantHitOut]:
        """The assistants whose description fits the query, among every one the caller may read. See
        AssistantSearchService for what it costs: nothing at all for a handful of assistants."""
        return await self._hits(user, await AssistantSearchService(self.db).search(user, query, limit))

    async def suggest(self, user: RequestContext, question: str, limit: int = 3) -> list[AssistantHitOut]:
        """The assistants worth proposing for a question - possibly none. Proposed, never applied."""
        return await self._hits(user, await AssistantSearchService(self.db).suggest(user, question, limit))

    async def _hits(self, user: RequestContext, hits: list) -> list[AssistantHitOut]:  # noqa: ANN001
        if not hits:
            return []
        rows = {a.id: w for a, w in await self.assistants.list_accessible(user.user_id, user.groups)}
        readable = await self._readable_collections(
            user, {uuid.UUID(cid) for hit in hits for cid in hit.assistant.collection_ids}
        )
        known = await self._known_names(user)
        counts = await self.assistants.share_counts([h.assistant.id for h in hits if self._owns(h.assistant, user)])
        out = []
        for hit in hits:
            base = self._present(
                hit.assistant, user, rows.get(hit.assistant.id, False), readable, counts.get(hit.assistant.id, 0), known
            )
            out.append(AssistantHitOut(**base.model_dump(), score=hit.score, score_kind=hit.kind))
        return out

    # --- consulting ---

    async def _consultable(self, user: RequestContext, assistant: Assistant, question: str) -> list[dict]:
        """The assistants this one may consult for the question (#531), each with the collections the caller may read.

        Which ones: none by default; "list", those its author named; "all", every assistant the caller may read. Never
        itself, and only those that have collections to search and at least one the caller can read. When more than
        `ASSISTANTS_CONSULT_MAX` qualify, the closest to the question are kept - by the hybrid search, with no model
        asked - and when that many or fewer do, all are, with no search. An assistant consulted is only ever read for
        its collections: its instructions are not applied, and it does not consult another one in turn."""
        if assistant.consult_mode == "none":
            return []
        search = AssistantSearchService(self.db)
        pool = [a for a in await search.readable(user) if a.id != assistant.id and a.collection_ids]
        if assistant.consult_mode == "list":
            wanted = set(assistant.consult_assistant_ids)
            pool = [a for a in pool if str(a.id) in wanted]
        readable = await self._readable_collections(user, {uuid.UUID(cid) for a in pool for cid in a.collection_ids})
        usable = {a.id: [cid for cid in a.collection_ids if uuid.UUID(cid) in readable] for a in pool}
        pool = [a for a in pool if usable[a.id]]
        chosen = await search.closest(pool, question, _settings.ASSISTANTS_CONSULT_MAX)
        return [
            {
                "id": str(a.id),
                "name": a.name,
                "description": a.description,
                "collection_ids": usable[a.id],
                "disabled_tools": list(a.disabled_tools),
            }
            for a in chosen
        ]

    async def _known_names(self, user: RequestContext) -> dict[uuid.UUID, str]:
        """The assistants the caller may read, by id: who they may be shown as consulting."""
        return {a.id: a.name for a, _ in await self.assistants.list_accessible(user.user_id, user.groups)}

    async def _designated_assistants(
        self, user: RequestContext, ids: list[uuid.UUID], exclude: set[uuid.UUID]
    ) -> list[str]:
        """Those of these assistants the author may read, never the assistant itself: nobody names one they cannot
        see."""
        known = await self._known_names(user)
        return [str(aid) for aid in dict.fromkeys(ids) if aid in known and aid not in exclude]

    # --- internals ---

    @staticmethod
    def _owns(assistant: Assistant, user: RequestContext) -> bool:
        return assistant.owner_id == user.user_id

    @staticmethod
    def _admin_over(assistant: Assistant, user: RequestContext) -> bool:
        """An administrator can take down what is public in the organisation, and nothing else."""
        return user.is_admin and assistant.visibility == CollectionVisibility.PUBLIC

    async def _get_readable(self, assistant_id: uuid.UUID, user: RequestContext) -> tuple[Assistant, bool]:
        found = await self.assistants.get_accessible(assistant_id, user.user_id, user.groups)
        if found is None:
            raise AssistantNotFoundError(str(assistant_id))
        return found

    async def _get_owned(self, assistant_id: uuid.UUID, user: RequestContext) -> Assistant:
        assistant, _ = await self._get_readable(assistant_id, user)
        if not self._owns(assistant, user):
            raise AssistantNotOwnedError
        return assistant

    async def _readable_collections(self, user: RequestContext, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Those of `ids` the user may read, with their names - by the same barrier as the chat."""
        if not ids:
            return {}
        accessible = await self.collections.filter_accessible_ids(list(ids), user.user_id, user.groups)
        rows = await self.collections.get_by_ids(list(accessible))
        return {collection.id: collection.name for collection in rows}

    def _present(
        self,
        assistant: Assistant,
        user: RequestContext,
        writable: bool,
        readable: dict[uuid.UUID, str],
        share_count: int,
        known_assistants: dict[uuid.UUID, str],
    ) -> AssistantOut:
        owner = self._owns(assistant, user)
        can_edit = writable or self._admin_over(assistant, user)
        shows_instructions = owner or writable or not assistant.hide_instructions
        designated = [uuid.UUID(cid) for cid in assistant.collection_ids]
        return AssistantOut(
            id=assistant.id,
            name=assistant.name,
            description=assistant.description,
            icon=assistant.icon,
            color=assistant.color,
            instructions=assistant.instructions if shows_instructions else None,
            instructions_hidden=not shows_instructions and bool(assistant.instructions),
            hide_instructions=assistant.hide_instructions,
            collections=[AssistantCollectionOut(id=cid, name=readable[cid]) for cid in designated if cid in readable],
            inaccessible_collection_count=sum(cid not in readable for cid in designated),
            include_descendants=assistant.include_descendants,
            web_search_allowed=assistant.web_search_allowed,
            disabled_tools=list(assistant.disabled_tools),
            consult_mode=assistant.consult_mode,
            consulted=[
                AssistantRefOut(id=uuid.UUID(aid), name=known_assistants[uuid.UUID(aid)])
                for aid in assistant.consult_assistant_ids
                if uuid.UUID(aid) in known_assistants
            ],
            inaccessible_consulted_count=sum(
                uuid.UUID(aid) not in known_assistants for aid in assistant.consult_assistant_ids
            ),
            suggestions=list(assistant.suggestions),
            visibility=assistant.visibility,
            version=assistant.version,
            is_owner=owner,
            can_edit=can_edit,
            share_count=share_count if owner else 0,
            created_at=assistant.created_at,
            updated_at=assistant.updated_at,
        )
