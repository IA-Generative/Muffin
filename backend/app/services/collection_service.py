import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.sharing import (
    hash_identifier,
    mask_email,
    mask_group,
    normalize_email,
    normalize_group,
)
from app.models.collection import Collection, CollectionVisibility, ShareSubjectType
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.repositories.run_repository import RunRepository
from app.schemas.collection import (
    ChunkOut,
    CollectionOut,
    CollectionPathItem,
    CollectionSettingsUpdate,
    CollectionUpdate,
    EntityMentionOut,
    EntityOut,
    GroundednessRunOut,
    GroundednessStatsOut,
    QaPairOut,
    RelationOut,
    RelationSourceOut,
    RelevantDocumentOut,
    ShareCreate,
    ShareOut,
)
from app.schemas.feedback import FeedbackStatsOut
from app.schemas.pagination import Page, PaginationParams
from app.services import embedding_model_lookup, vector_store
from app.services.collection_hierarchy_service import CollectionHierarchyService
from app.services.description_rollup_service import DescriptionRollupService

# Last resort only, when the hub is unreachable/unconfigured and there's nothing else to go on -
# see create_collection, which otherwise resolves the admin-configured or hub-discovered model.
FALLBACK_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_COLLECTION_NAME = "Nouvelle collection"


class CollectionNotFoundError(Exception):
    pass


class ParentCollectionNotFoundError(Exception):
    """The requested parent of a sub-collection doesn't exist or isn't the caller's - kept apart
    from CollectionNotFoundError so the router can say which of the two ids was wrong."""


class CollectionNotEditableError(Exception):
    """The collection is visible to the caller but they may not edit its living documents - they
    are neither its owner nor an administrator (see services/editing_rights.py)."""


class ShareNotFoundError(Exception):
    pass


class AlreadyInvitedError(Exception):
    """A share for this exact identifier already exists on this collection - the owner's own
    prior action, not information about a third party, so it's fine to surface as-is (unlike the
    live email-existence lookup this design deliberately avoids)."""


def _display_name(user: RequestContext) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email


class CollectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = CollectionRepository(db)
        self.hierarchy = CollectionHierarchyRepository(db)
        self.hierarchy_rules = CollectionHierarchyService(db)
        self.description_rollup = DescriptionRollupService(db)
        self.qa_pairs = QaPairRepository(db)
        self.entities = EntityRepository(db)
        self.runs = RunRepository(db)
        self.feedbacks = FeedbackRepository(db)
        self.chunks = ChunkRepository(db)

    async def list_collections(
        self, user: RequestContext, pagination: PaginationParams, *, roots_only: bool = False
    ) -> Page[CollectionOut]:
        collections, total = await self.repository.list_accessible(
            user.user_id,
            user.groups,
            limit=pagination.limit,
            offset=pagination.offset,
            exclude_temporary=True,
            roots_only=roots_only,
        )
        return pagination.to_page(await self._present_many(collections, user), total)

    async def list_children(
        self, collection_id: uuid.UUID, user: RequestContext, pagination: PaginationParams
    ) -> Page[CollectionOut]:
        await self._get_accessible(collection_id, user)
        collections, total = await self.repository.list_accessible(
            user.user_id,
            user.groups,
            limit=pagination.limit,
            offset=pagination.offset,
            exclude_temporary=True,
            parent_id=collection_id,
        )
        return pagination.to_page(await self._present_many(collections, user), total)

    async def create_collection(
        self,
        user: RequestContext,
        *,
        name: str | None = None,
        description: str | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> CollectionOut:
        parent = await self._get_owned_parent(parent_id, user) if parent_id is not None else None
        if parent is not None:
            # A sub-collection starts from a copy of its parent's settings (#215), embedding
            # model included, rather than from the platform defaults.
            embedding_model = parent.settings.embedding_model
        else:
            embedding_model = await embedding_model_lookup.default_embedding_model(self.db) or FALLBACK_EMBEDDING_MODEL
        collection = await self.repository.create(
            owner_id=user.user_id,
            name=name or DEFAULT_COLLECTION_NAME,
            description=description or "",
            embedding_model=embedding_model,
            settings_template=parent.settings if parent is not None else None,
        )
        # Raises before the commit below on a broken rule, so nothing is created.
        await self.hierarchy_rules.set_parent(collection, parent)
        await self.db.commit()
        # Attaching to a parent is an UPDATE after the INSERT, which expires updated_at - same
        # reload as update_collection.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return await self._present(collection, user)

    async def get_collection(self, collection_id: uuid.UUID, user: RequestContext) -> CollectionOut:
        collection = await self._get_accessible(collection_id, user)
        return await self._present(collection, user)

    async def update_collection(
        self, collection_id: uuid.UUID, user: RequestContext, update: CollectionUpdate
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        updated_by = _display_name(user)
        previous_parent_id = collection.parent_id
        previous_description = collection.description

        if "parent_id" in update.model_fields_set:
            parent = await self._get_owned_parent(update.parent_id, user) if update.parent_id is not None else None
            # Raises before any commit on a broken rule (cycle, temporary collection), so the
            # other fields of this same request aren't half-applied either.
            await self.hierarchy_rules.set_parent(collection, parent)

        if update.name is not None and update.name.strip():
            await self.repository.update_name(collection, update.name.strip())
        if update.description is not None:
            await self.repository.update_description(collection, update.description, updated_by)
        if update.tags is not None:
            await self.repository.update_tags(collection, update.tags, updated_by)

        await self._schedule_parent_rollups(collection, previous_parent_id, previous_description)
        await self.db.commit()
        # tags/settings are already correct in memory (mutated directly above),
        # this is only to reload updated_at - onupdate=func.now() expires it
        # after the UPDATE, and accessing it later outside an active await
        # crashes with MissingGreenlet instead of lazy-loading like sync ORM would.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return await self._present(collection, user)

    async def update_settings(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        update: CollectionSettingsUpdate,
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)

        await self.repository.update_settings(
            collection,
            chunking_strategy=update.chunking_strategy,
            chunk_size=update.chunk_size,
            chunk_overlap=update.chunk_overlap,
            embedding_model=update.embedding_model,
            instructions=(update.instructions.model_dump() if update.instructions is not None else None),
            # exclude_unset, not model_dump(): only the keys the caller sent
            # should be merged in - the schema defaults every field to None,
            # so a full dump would overwrite the others with None too.
            generation_models=(
                update.generation_models.model_dump(exclude_unset=True)
                if update.generation_models is not None
                else None
            ),
            pipeline_windows=(
                update.pipeline_windows.model_dump(exclude_unset=True) if update.pipeline_windows is not None else None
            ),
        )

        # No refresh needed: only collection_settings columns changed (none
        # with a server-side onupdate), so nothing on `collection` is expired.
        await self.db.commit()
        return await self._present(collection, user)

    async def list_qa_pairs(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID | None = None,
    ) -> list[QaPairOut]:
        await self._get_accessible(collection_id, user)
        pairs = await self.qa_pairs.list_by_collection(collection_id, document_id)
        relevant_ids = {uuid.UUID(i) for pair in pairs for i in (pair.relevant_document_ids or [])}
        names = await self.qa_pairs.document_names(collection_id, list(relevant_ids))
        return [
            QaPairOut(
                id=pair.id,
                question=pair.question,
                answer=pair.answer,
                source=pair.document.name if pair.document else None,
                source_document_id=pair.document_id if pair.source_page and pair.source_excerpt else None,
                source_page=pair.source_page,
                source_excerpt=pair.source_excerpt,
                source_start=pair.source_start if pair.source_page and pair.source_excerpt else None,
                source_end=pair.source_end if pair.source_page and pair.source_excerpt else None,
                origin=pair.origin,
                validated=pair.validated,
                golden=pair.golden,
                relevant_documents=[
                    RelevantDocumentOut(id=uuid.UUID(i), name=names[i])
                    for i in (pair.relevant_document_ids or [])
                    if i in names
                ],
            )
            for pair in pairs
        ]

    async def list_chunks(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        pagination: PaginationParams,
    ) -> Page[ChunkOut]:
        await self._get_accessible(collection_id, user)
        rows, total = await self.chunks.list_by_collection(
            collection_id, limit=pagination.limit, offset=pagination.offset
        )
        return pagination.to_page(
            [
                ChunkOut(
                    id=chunk.id,
                    document_name=document_name,
                    index=chunk.index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                )
                for chunk, document_name in rows
            ],
            total,
        )

    async def get_groundedness_stats(self, collection_id: uuid.UUID, user: RequestContext) -> GroundednessStatsOut:
        await self._get_accessible(collection_id, user)
        stats = await self.runs.get_groundedness_stats(collection_id)
        return GroundednessStatsOut(
            evaluated_count=stats["evaluated_count"],
            ungrounded_count=stats["ungrounded_count"],
            recent_ungrounded=[GroundednessRunOut(**run) for run in stats["recent_ungrounded"]],
        )

    async def get_feedback_stats(self, collection_id: uuid.UUID, user: RequestContext) -> FeedbackStatsOut:
        await self._get_accessible(collection_id, user)
        stats = await self.feedbacks.get_stats(collection_id)
        return FeedbackStatsOut(**stats)

    async def list_entities(self, collection_id: uuid.UUID, user: RequestContext) -> list[EntityOut]:
        await self._get_accessible(collection_id, user)
        entities = await self.entities.list_by_collection(collection_id)
        located = await self.entities.occurrence_counts([entity.id for entity in entities])
        return [
            EntityOut(
                id=entity.id,
                name=entity.name,
                type=entity.type,
                mentions=entity.mentions,
                occurrences=located.get(entity.id, 0),
            )
            for entity in entities
        ]

    async def list_relations(self, collection_id: uuid.UUID, user: RequestContext) -> list[RelationOut]:
        await self._get_accessible(collection_id, user)
        relations = await self.entities.list_relations_by_collection(collection_id)
        return await self._relations_out(relations)

    async def _relations_out(self, relations) -> list[RelationOut]:
        names = await self.entities.document_names(
            list({relation.document_id for relation in relations if relation.document_id is not None})
        )
        return [
            RelationOut(
                id=relation.id,
                from_entity=relation.from_entity.name,
                to=relation.to_entity.name,
                type=relation.type,
                # The sentence behind it (#352), when it has one and its document is still there.
                source=(
                    RelationSourceOut(
                        document_id=relation.document_id,
                        document_name=names[relation.document_id],
                        page_number=relation.source_page,
                        passage=relation.source_excerpt,
                        start=relation.source_start,
                        end=relation.source_end,
                    )
                    if relation.source_page and relation.source_excerpt and relation.document_id in names
                    else None
                ),
            )
            for relation in relations
        ]

    async def list_entity_mentions(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        entity_id: uuid.UUID,
        document_id: uuid.UUID | None = None,
    ) -> list[EntityMentionOut]:
        """The occurrences of an entity in the text (#352), in the order one reads them: what a source modal pages
        through. In one document when asked. Empty for an entity of another collection, or not found in the text."""
        await self._get_accessible(collection_id, user)
        rows = await self.entities.list_mentions(collection_id, entity_id, document_id)
        return [
            EntityMentionOut(
                document_id=mention.document_id,
                document_name=name,
                page_number=mention.page_number,
                start=mention.char_start,
                end=mention.char_end,
            )
            for mention, name in rows
        ]

    async def delete_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        collection = await self._get_owned(collection_id, user)
        # The whole sub-collection subtree goes with it (ON DELETE CASCADE on parent_id, #213) -
        # a descendant always has the same owner, so the ownership check above covers it too.
        subtree_ids = [collection_id, *await self.hierarchy.descendant_ids(collection_id)]
        # Collected before the cascade delete removes the rows that reference
        # them - Postgres cleanup and RustFS cleanup can't be one transaction.
        rustfs_keys = await self.repository.list_rustfs_keys(subtree_ids)
        if collection.description:
            # Its parent's rolled-up description no longer has this sub-collection to draw from.
            await self.description_rollup.schedule(collection.parent_id)
        await self.repository.delete(collection)
        await self.db.commit()
        # Best-effort and after the commit: a RustFS/Qdrant failure here must
        # not roll back a deletion the user already sees as done.
        storage.delete_objects(rustfs_keys)
        for deleted_id in subtree_ids:
            vector_store.delete_collection(deleted_id)

    async def update_visibility(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        visibility: CollectionVisibility,
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        await self.repository.update_visibility(collection, visibility)
        await self.db.commit()
        # Same reasoning as update_collection: onupdate=func.now() expires updated_at after the
        # UPDATE regardless of expire_on_commit, so it needs an explicit reload before use.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return await self._present(collection, user)

    async def create_share(self, collection_id: uuid.UUID, user: RequestContext, create: ShareCreate) -> ShareOut:
        """Never looks the identifier up anywhere (Keycloak or otherwise) - only ever creates a
        PENDING row from its hash. See app/core/sharing.py for why: confirming or denying that an
        identifier resolves to a real account/group is exactly the enumeration risk this design
        avoids, and the response here must never depend on whether it does."""
        await self._get_owned(collection_id, user)

        if create.subject_type == ShareSubjectType.USER:
            normalized = normalize_email(create.identifier)
            display_hint = mask_email(normalized)
        else:
            normalized = normalize_group(create.identifier)
            display_hint = mask_group(normalized)

        try:
            share = await self.repository.create_share(
                collection_id,
                create.subject_type,
                hash_identifier(normalized),
                display_hint,
            )
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()
            raise AlreadyInvitedError(str(collection_id)) from error
        return ShareOut.from_model(share)

    async def list_shares(self, collection_id: uuid.UUID, user: RequestContext) -> list[ShareOut]:
        """Its own shares first, then the ones inherited from its ancestors (#216), nearest
        ancestor first. The caller owns the whole tree (a child always has its parent's owner),
        so every ancestor here is one they can see."""
        await self._get_owned(collection_id, user)
        ancestors = (await self.hierarchy.ancestor_chains([collection_id])).get(collection_id, [])
        shares = await self.repository.list_shares([collection_id, *(ancestor.id for ancestor in ancestors)])

        own = [ShareOut.from_model(share) for share in shares if share.collection_id == collection_id]
        inherited = []
        for ancestor in ancestors:
            source = CollectionPathItem(id=ancestor.id, name=ancestor.name)
            inherited += [
                ShareOut.from_model(share, inherited_from=source)
                for share in shares
                if share.collection_id == ancestor.id
            ]
        return own + inherited

    async def delete_share(self, collection_id: uuid.UUID, user: RequestContext, share_id: uuid.UUID) -> None:
        await self._get_owned(collection_id, user)
        share = await self.repository.get_share(collection_id, share_id)
        if share is None:
            raise ShareNotFoundError(str(share_id))
        await self.repository.delete_share(share)
        await self.db.commit()

    async def _get_owned(self, collection_id: uuid.UUID, user: RequestContext) -> Collection:
        collection = await self.repository.get(collection_id, user.user_id)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        return collection

    async def _get_accessible(self, collection_id: uuid.UUID, user: RequestContext) -> Collection:
        collection = await self.repository.get_accessible(collection_id, user.user_id, user.groups)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        return collection

    async def _schedule_parent_rollups(
        self, collection: Collection, previous_parent_id: uuid.UUID | None, previous_description: str
    ) -> None:
        """A parent's description is rolled up from its sub-collections' descriptions (#218), so it
        needs recomputing when one of them changes, or when a described sub-collection moves in or
        out of it. A collection without a description contributes nothing either way."""
        if collection.parent_id != previous_parent_id:
            if previous_description:
                await self.description_rollup.schedule(previous_parent_id)
            if collection.description:
                await self.description_rollup.schedule(collection.parent_id)
        elif collection.description != previous_description:
            await self.description_rollup.schedule(collection.parent_id)

    async def _get_owned_parent(self, parent_id: uuid.UUID, user: RequestContext) -> Collection:
        """Only the owner may put a collection under another one - readable isn't enough."""
        parent = await self.repository.get(parent_id, user.user_id)
        if parent is None:
            raise ParentCollectionNotFoundError(str(parent_id))
        return parent

    async def _present(self, collection: Collection, user: RequestContext) -> CollectionOut:
        return (await self._present_many([collection], user))[0]

    async def _present_many(self, collections: Sequence[Collection], user: RequestContext) -> list[CollectionOut]:
        """CollectionOut with its place in the tree (#215), batched for a whole page: one query
        for every ancestor chain, one for every child, one access check over both."""
        ids = [collection.id for collection in collections]
        chains = await self.hierarchy.ancestor_chains(ids)
        children = await self.hierarchy.child_ids_by_parent(ids)
        related_ids = {ancestor.id for chain in chains.values() for ancestor in chain}
        related_ids |= {child_id for child_ids in children.values() for child_id in child_ids}
        readable = await self.repository.filter_accessible_ids(list(related_ids), user.user_id, user.groups)
        document_counts = await self.repository.document_counts(ids)

        presented = []
        for collection in collections:
            path: list[CollectionPathItem] = []
            inherited_public_from = None
            # Nearest first: stop at the first unreadable ancestor, what's above it stays hidden.
            # A public ancestor is never above an unreadable one - it makes its whole subtree
            # readable - so the nearest public one is always found before the walk stops.
            for ancestor in chains.get(collection.id, []):
                if ancestor.id not in readable:
                    break
                item = CollectionPathItem(id=ancestor.id, name=ancestor.name)
                path.append(item)
                if (
                    inherited_public_from is None
                    and collection.visibility != CollectionVisibility.PUBLIC
                    and ancestor.visibility == CollectionVisibility.PUBLIC
                ):
                    inherited_public_from = item
            path.reverse()
            children_count = sum(child_id in readable for child_id in children.get(collection.id, []))
            presented.append(
                CollectionOut.from_model(
                    collection,
                    user.user_id,
                    path=path,
                    children_count=children_count,
                    document_counts=document_counts.get(collection.id, (0, 0)),
                    inherited_public_from=inherited_public_from,
                )
            )
        return presented
