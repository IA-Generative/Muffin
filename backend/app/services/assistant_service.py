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
    AssistantOut,
    AssistantUpdate,
)
from app.schemas.collection import ShareCreate, ShareOut, ShareUpdate
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
        return [
            self._present(assistant, user, writable, readable, counts.get(assistant.id, 0))
            for assistant, writable in rows
        ]

    async def get(self, assistant_id: uuid.UUID, user: RequestContext) -> AssistantOut:
        assistant, writable = await self._get_readable(assistant_id, user)
        readable = await self._readable_collections(user, {uuid.UUID(cid) for cid in assistant.collection_ids})
        counts = await self.assistants.share_counts([assistant.id]) if self._owns(assistant, user) else {}
        return self._present(assistant, user, writable, readable, counts.get(assistant.id, 0))

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
            suggestions=body.suggestions,
        )
        await self.db.commit()
        await self.db.refresh(assistant)
        logger.info(f"Assistant {assistant.id} ({assistant.name!r}) created by {user.user_id}")
        return await self.get(assistant.id, user)

    async def update(self, assistant_id: uuid.UUID, user: RequestContext, body: AssistantUpdate) -> AssistantOut:
        assistant, writable = await self._get_readable(assistant_id, user)
        if not (writable or self._admin_over(assistant, user)):
            raise AssistantNotEditableError
        changes = {
            key: value.strip() if key in ("description", "instructions") else value
            for key, value in body.model_dump(exclude_unset=True, exclude={"collection_ids"}).items()
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
        changed = {key: value for key, value in changes.items() if getattr(assistant, key) != value}
        if changed:
            for key, value in changed.items():
                setattr(assistant, key, value)
            assistant.version += 1
            await self.db.commit()
            await self.db.refresh(assistant)
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

    async def resolve(self, user: RequestContext, assistant_id: uuid.UUID) -> ResolvedAssistant:
        """What a chat with this assistant uses, independent of any route (the OpenAI-compatible API and the MCP server
        reuse it). The collections are those the assistant designates that **this** user may read."""
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
        )

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
            suggestions=list(assistant.suggestions),
            visibility=assistant.visibility,
            version=assistant.version,
            is_owner=owner,
            can_edit=can_edit,
            share_count=share_count if owner else 0,
            created_at=assistant.created_at,
            updated_at=assistant.updated_at,
        )
