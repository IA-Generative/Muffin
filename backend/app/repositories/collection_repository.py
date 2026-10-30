import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, exists, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.models.collection import (
    Collection,
    CollectionSettings,
    CollectionShare,
    CollectionTag,
    CollectionVisibility,
    SharePermission,
    ShareStatus,
    ShareSubjectType,
)
from app.models.document import Document, DocumentPage, DocumentStatus
from app.models.document_tabular_profile import DocumentTabularProfile
from app.models.document_tabular_sheet import DocumentTabularSheet
from app.repositories.document_repository import legacy_tabular_copy_key


class CollectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _base_query(self):
        return select(Collection).options(selectinload(Collection.tags), selectinload(Collection.settings))

    def _accessible_where(self, user_id: str, group_ids: Sequence[str]):
        """The collection itself or one of its ancestors is granted to the caller (see
        _granted_where) - read access is inherited down the sub-collection tree (#216), never
        up it. The single permission barrier both the UI listing and the research agent's VDB
        routing (GET /internal/users/{user_id}/accessible-collections) must agree on.

        Walks top-down from every granted collection rather than up from each candidate row: one
        recursive CTE per query, whatever the number of rows it filters. UNION is the cycle
        guard, same as CollectionHierarchyRepository.descendant_ids."""
        granted = aliased(Collection)
        readable = select(granted.id).where(self._granted_where(granted, user_id, group_ids))
        readable = readable.cte("readable", recursive=True)
        child = aliased(Collection)
        readable = readable.union(select(child.id).where(child.parent_id == readable.c.id))
        return Collection.id.in_(select(readable.c.id))

    def _accessible_among_where(
        self, collection_ids: Sequence[uuid.UUID], user_id: str, group_ids: Sequence[str], *, write: bool = False
    ):
        """Same barrier as _accessible_where, for a known set of ids: walks up from those ids
        (a handful of rows each) instead of down from everything the caller can read, which
        is what every lookup of a single collection needs - see the #216 benchmark.

        UNION over (start_id, node_id) is the cycle guard."""
        start = aliased(Collection)
        chain = (
            select(start.id.label("start_id"), start.id.label("node_id"))
            .where(start.id.in_(collection_ids))
            .cte("self_and_ancestors", recursive=True)
        )
        step = aliased(Collection)
        chain = chain.union(
            select(chain.c.start_id, step.parent_id).where(step.id == chain.c.node_id, step.parent_id.is_not(None))
        )
        granted = aliased(Collection)
        readable_ids = (
            select(chain.c.start_id)
            .join(granted, granted.id == chain.c.node_id)
            .where(
                self._write_granted_where(granted, user_id, group_ids)
                if write
                else self._granted_where(granted, user_id, group_ids)
            )
        )
        return Collection.id.in_(readable_ids)

    @staticmethod
    def _granted_where(target, user_id: str, group_ids: Sequence[str]):
        """owner OR public OR an ACTIVE direct share OR an ACTIVE share to one of the caller's
        groups, on `target` itself - before any inheritance from its ancestors."""
        direct_share = exists().where(
            CollectionShare.collection_id == target.id,
            CollectionShare.subject_type == ShareSubjectType.USER,
            CollectionShare.status == ShareStatus.ACTIVE,
            CollectionShare.subject_id == user_id,
        )
        group_share = (
            exists().where(
                CollectionShare.collection_id == target.id,
                CollectionShare.subject_type == ShareSubjectType.GROUP,
                CollectionShare.status == ShareStatus.ACTIVE,
                CollectionShare.subject_id.in_(group_ids),
            )
            if group_ids
            else false()
        )
        return or_(
            target.owner_id == user_id,
            target.visibility == CollectionVisibility.PUBLIC,
            direct_share,
            group_share,
        )

    @staticmethod
    def _write_granted_where(target, user_id: str, group_ids: Sequence[str]):
        """owner OR an ACTIVE share that lets write, direct or to one of the caller's groups, on `target`
        itself (#454). A public collection lets read, never write."""
        direct = exists().where(
            CollectionShare.collection_id == target.id,
            CollectionShare.subject_type == ShareSubjectType.USER,
            CollectionShare.status == ShareStatus.ACTIVE,
            CollectionShare.permission == SharePermission.WRITE,
            CollectionShare.subject_id == user_id,
        )
        group = (
            exists().where(
                CollectionShare.collection_id == target.id,
                CollectionShare.subject_type == ShareSubjectType.GROUP,
                CollectionShare.status == ShareStatus.ACTIVE,
                CollectionShare.permission == SharePermission.WRITE,
                CollectionShare.subject_id.in_(group_ids),
            )
            if group_ids
            else false()
        )
        return or_(target.owner_id == user_id, direct, group)

    async def filter_editable_ids(
        self, collections: Sequence[Collection], user_id: str, group_ids: Sequence[str], is_admin: bool
    ) -> set[uuid.UUID]:
        """The collections, among these the caller can already read, that they may also change (#454): their
        own, those where a share lets them write on the collection or on an ancestor (write is inherited down
        the tree like read, #216), and - for a platform administrator - all of them."""
        if is_admin:
            return {collection.id for collection in collections}
        editable = {collection.id for collection in collections if collection.owner_id == user_id}
        others = [collection.id for collection in collections if collection.id not in editable]
        if others:
            result = await self.db.scalars(
                select(Collection.id).where(self._accessible_among_where(others, user_id, group_ids, write=True))
            )
            editable |= set(result.all())
        return editable

    async def list_accessible(
        self,
        user_id: str,
        group_ids: Sequence[str],
        *,
        limit: int,
        offset: int,
        exclude_temporary: bool = False,
        roots_only: bool = False,
        parent_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[Collection], int]:
        """Flat across the whole sub-collection tree by default (#215); `roots_only` keeps only
        top-level collections, `parent_id` only the direct children of that collection."""
        where = self._accessible_where(user_id, group_ids)
        if exclude_temporary:
            # The user-facing listing (§ conv-files) - a temporary collection is conversation-
            # scoped and auto-pinned (see RunService.create_run), never something the user picks
            # from a list of their collections. list_all_accessible below must NOT get this
            # filter: the agent's pinned/accessible intersection still needs to find it there.
            where = where & (Collection.is_temporary.is_(False))
        if roots_only:
            where = where & (Collection.parent_id.is_(None))
        if parent_id is not None:
            where = where & (Collection.parent_id == parent_id)

        total = await self.db.scalar(select(func.count()).select_from(Collection).where(where))

        result = await self.db.execute(
            self._base_query().where(where).order_by(Collection.updated_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total or 0

    async def accessible_ids(self, user_id: str, group_ids: Sequence[str]) -> set[uuid.UUID]:
        """Just the ids of the collections the user can read, never a conversation's temporary one -
        for a query that only needs to filter by them, without loading every collection."""
        result = await self.db.scalars(
            select(Collection.id).where(self._accessible_where(user_id, group_ids), Collection.is_temporary.is_(False))
        )
        return set(result.all())

    async def list_all_accessible(self, user_id: str, group_ids: Sequence[str]) -> Sequence[Collection]:
        """Unpaginated - for server-side permission checks (e.g. the research
        agent's "which collections can this user's query even reach"), not
        for a UI listing."""
        result = await self.db.execute(self._base_query().where(self._accessible_where(user_id, group_ids)))
        return result.scalars().all()

    async def filter_accessible_ids(
        self, collection_ids: Sequence[uuid.UUID], user_id: str, group_ids: Sequence[str]
    ) -> set[uuid.UUID]:
        """The subset of these ids the user can read - same barrier as list_accessible, for a
        batch of ids found some other way (e.g. a page's ancestors and children, #215)."""
        if not collection_ids:
            return set()
        result = await self.db.scalars(
            select(Collection.id).where(self._accessible_among_where(collection_ids, user_id, group_ids))
        )
        return set(result.all())

    async def document_counts(self, collection_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
        """(documents, indexed documents) per collection, in one query for a whole page - so a
        collection card can show its counts without loading the documents themselves."""
        if not collection_ids:
            return {}
        result = await self.db.execute(
            select(
                Document.collection_id,
                func.count(),
                func.count().filter(Document.status == DocumentStatus.INDEXED),
            )
            .where(Document.collection_id.in_(collection_ids))
            .group_by(Document.collection_id)
        )
        return {collection_id: (total, indexed) for collection_id, total, indexed in result.all()}

    async def sibling_names(self, owner_id: str, parent_id: uuid.UUID | None) -> set[str]:
        """Names of this owner's collections at one level of the tree (top level for None) - to
        give a new one a name that doesn't clash, e.g. a ZIP imported twice (#223)."""
        level = Collection.parent_id.is_(None) if parent_id is None else Collection.parent_id == parent_id
        result = await self.db.scalars(
            select(Collection.name).where(Collection.owner_id == owner_id, Collection.is_temporary.is_(False), level)
        )
        return set(result.all())

    async def list_owned_ids(self, owner_id: str) -> Sequence[uuid.UUID]:
        """Every non-temporary collection this user owns (§122) - the candidate set a filing
        suggestion is allowed to point at, since only the owner can add a document to a
        collection today (CollectionService._get_owned). Never public/shared collections, even
        though those are readable - writing a document into one isn't, so suggesting one would
        be a suggestion the user could never actually accept."""
        result = await self.db.scalars(
            select(Collection.id).where(Collection.owner_id == owner_id, Collection.is_temporary.is_(False))
        )
        return result.all()

    async def get(self, collection_id: uuid.UUID, owner_id: str) -> Collection | None:
        result = await self.db.execute(
            self._base_query().where(Collection.id == collection_id, Collection.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def get_accessible(
        self, collection_id: uuid.UUID, user_id: str, group_ids: Sequence[str]
    ) -> Collection | None:
        """Same permission barrier as list_accessible/list_all_accessible, for a single
        collection - read access for owner/public/shared, not just the "is it mine" check `get`
        does for owner-only write operations."""
        result = await self.db.execute(
            self._base_query().where(self._accessible_among_where([collection_id], user_id, group_ids))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, collection_id: uuid.UUID) -> Collection | None:
        """No owner check - internal/worker use only, never exposed on a
        user-facing route."""
        result = await self.db.execute(self._base_query().where(Collection.id == collection_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, collection_ids: Sequence[uuid.UUID]) -> Sequence[Collection]:
        """No owner check, same reasoning as get_by_id - bulk variant for resolving a list of
        candidate ids (e.g. a filing suggestion's top-K) into name/description in one query."""
        if not collection_ids:
            return []
        result = await self.db.execute(self._base_query().where(Collection.id.in_(collection_ids)))
        return result.scalars().all()

    async def count_documents(self, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many documents each collection has - for the research agent to answer "how many
        documents are in X" without listing them all (§ meta-query tools)."""
        if not collection_ids:
            return {}
        result = await self.db.execute(
            select(Document.collection_id, func.count(Document.id))
            .where(Document.collection_id.in_(collection_ids))
            .group_by(Document.collection_id)
        )
        return dict(result.all())

    async def get_embedding_models(self, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Which embedding model each collection's chunks were embedded with (§12: VDB routing
        picks collections, but the query itself must be embedded once per distinct model among
        them before searching each one's own Qdrant index)."""
        # The model of the vectors in the active index, which is the configured one unless the owner
        # picked another model and the index hasn't been rebuilt with it yet (#12).
        result = await self.db.execute(
            select(
                CollectionSettings.collection_id,
                func.coalesce(CollectionSettings.index_embedding_model, CollectionSettings.embedding_model),
            ).where(CollectionSettings.collection_id.in_(collection_ids))
        )
        return dict(result.all())

    async def get_external_ids(self, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        """(source, id in the other system) of the collections copied from another system (#453) that Muffin has
        not taken over (#462): what is searched where it is, not in an index of Muffin's."""
        result = await self.db.execute(
            select(Collection.id, Collection.source, Collection.external_id).where(
                Collection.id.in_(collection_ids),
                Collection.external_id.is_not(None),
                Collection.adopted_at.is_(None),
            )
        )
        return {collection_id: (source, external_id) for collection_id, source, external_id in result.all()}

    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str = "",
        embedding_model: str,
        settings_template: CollectionSettings | None = None,
    ) -> Collection:
        """`settings_template` (a sub-collection's parent settings, #215) is copied, not shared:
        the new collection can change its own settings afterwards without touching the parent."""
        collection = Collection(owner_id=owner_id, name=name, description=description)
        if settings_template is None:
            collection.settings = CollectionSettings(embedding_model=embedding_model)
        else:
            collection.settings = CollectionSettings(
                embedding_model=settings_template.embedding_model,
                chunking_strategy=settings_template.chunking_strategy,
                chunk_size=settings_template.chunk_size,
                chunk_overlap=settings_template.chunk_overlap,
                instructions_qa=settings_template.instructions_qa,
                instructions_extraction=settings_template.instructions_extraction,
                instructions_chunking=settings_template.instructions_chunking,
                instructions_tagging=settings_template.instructions_tagging,
                instructions_summary=settings_template.instructions_summary,
                generation_models=dict(settings_template.generation_models or {}) or None,
                pipeline_windows=dict(settings_template.pipeline_windows or {}) or None,
                caption_engine=settings_template.caption_engine,
                caption_model=settings_template.caption_model,
            )
        self.db.add(collection)
        await self.db.flush()
        await self.db.refresh(collection, attribute_names=["tags", "settings"])
        return collection

    async def get_temporary_for_conversation(self, conversation_id: uuid.UUID) -> Collection | None:
        """The collection backing files uploaded directly into this conversation (§ conv-files),
        or None if nothing has been uploaded into it yet - never creates one, see
        get_or_create_temporary_for_conversation for the lazy-create path."""
        result = await self.db.execute(self._base_query().where(Collection.conversation_id == conversation_id))
        return result.scalar_one_or_none()

    async def get_or_create_temporary_for_conversation(
        self, conversation_id: uuid.UUID, owner_id: str, *, embedding_model: str
    ) -> Collection:
        """Lazy, idempotent: called on every file upload into a conversation, only the first
        call actually creates the collection (uq_collections_conversation_id makes a second one
        for the same conversation impossible even under a race - the loser's INSERT just fails
        and the caller would retry into the now-existing row)."""
        existing = await self.get_temporary_for_conversation(conversation_id)
        if existing is not None:
            return existing

        collection = Collection(
            owner_id=owner_id,
            name="Fichiers de la conversation",
            description="",
            visibility=CollectionVisibility.PRIVATE,
            is_temporary=True,
            conversation_id=conversation_id,
        )
        collection.settings = CollectionSettings(embedding_model=embedding_model)
        self.db.add(collection)
        await self.db.flush()
        await self.db.refresh(collection, attribute_names=["tags", "settings"])
        return collection

    async def get_personal_holding(self, owner_id: str) -> Collection | None:
        """This user's standalone-upload holding collection (§122's "Fichiers à ranger" page -
        upload a file there with no conversation at all), or None if they've never used it."""
        result = await self.db.execute(
            self._base_query().where(
                Collection.owner_id == owner_id,
                Collection.is_temporary.is_(True),
                Collection.conversation_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_personal_holding(self, owner_id: str, *, embedding_model: str) -> Collection:
        """Lazy, idempotent - same reasoning as get_or_create_temporary_for_conversation, one per
        user rather than one per conversation (uq_collections_owner_holding is the race guard)."""
        existing = await self.get_personal_holding(owner_id)
        if existing is not None:
            return existing

        collection = Collection(
            owner_id=owner_id,
            name="Fichiers à ranger",
            description="",
            visibility=CollectionVisibility.PRIVATE,
            is_temporary=True,
        )
        collection.settings = CollectionSettings(embedding_model=embedding_model)
        self.db.add(collection)
        await self.db.flush()
        await self.db.refresh(collection, attribute_names=["tags", "settings"])
        return collection

    async def update_name(self, collection: Collection, name: str) -> None:
        collection.name = name

    async def update_description(self, collection: Collection, description: str, updated_by: str) -> None:
        collection.description = description
        collection.description_updated_by = updated_by
        collection.description_updated_at = datetime.now(UTC)

    async def update_tags(self, collection: Collection, tags: list[str], updated_by: str) -> None:
        await self.db.execute(delete(CollectionTag).where(CollectionTag.collection_id == collection.id))
        collection.tags = [CollectionTag(collection_id=collection.id, tag=tag) for tag in dict.fromkeys(tags)]
        collection.tags_updated_by = updated_by
        collection.tags_updated_at = datetime.now(UTC)

    async def update_settings(
        self,
        collection: Collection,
        *,
        chunking_strategy: str | None,
        chunk_size: int | None,
        chunk_overlap: int | None,
        embedding_model: str | None,
        instructions: dict[str, str] | None,
        generation_models: dict[str, str | None] | None,
        pipeline_windows: dict[str, Any] | None,
        caption_engine: str | None = None,
        caption_model: str | None = None,
    ) -> bool:
        """Returns whether the embedding model actually changed - the caller
        uses that to flip reindex_required."""
        settings = collection.settings
        embedding_model_changed = embedding_model is not None and embedding_model != settings.embedding_model

        if chunking_strategy is not None:
            settings.chunking_strategy = chunking_strategy
        if chunk_size is not None:
            settings.chunk_size = chunk_size
        if chunk_overlap is not None:
            settings.chunk_overlap = chunk_overlap
        if embedding_model_changed:
            # The index keeps its vectors - and search the model they were made with - until it is
            # rebuilt with the new one (#12): queries stay comparable to what the index holds.
            index_model = settings.index_embedding_model or settings.embedding_model
            settings.embedding_model = embedding_model
            settings.index_embedding_model = None if embedding_model == index_model else index_model
            settings.reindex_required = embedding_model != index_model
        if instructions is not None:
            settings.instructions_qa = instructions["qa"]
            settings.instructions_extraction = instructions["extraction"]
            settings.instructions_chunking = instructions["chunking"]
            settings.instructions_tagging = instructions["tagging"]
            settings.instructions_summary = instructions["summary"]
        if generation_models is not None:
            settings.generation_models = {**(settings.generation_models or {}), **generation_models}
        if pipeline_windows is not None:
            settings.pipeline_windows = {**(settings.pipeline_windows or {}), **pipeline_windows}
        if caption_engine is not None:
            settings.caption_engine = caption_engine
        if caption_model is not None:
            settings.caption_model = caption_model or None

        return embedding_model_changed

    async def list_rustfs_keys(self, collection_ids: Sequence[uuid.UUID]) -> list[str]:
        """Every RustFS object under these collections - uploaded files and page
        screenshots - collected before the cascade delete removes the rows
        that reference them. Several ids because deleting a collection deletes
        its whole sub-collection subtree with it (#213)."""
        storage_keys = await self.db.scalars(
            select(Document.storage_key).where(
                Document.collection_id.in_(collection_ids), Document.storage_key.is_not(None)
            )
        )
        screenshot_keys = await self.db.scalars(
            select(DocumentPage.screenshot)
            .join(Document, DocumentPage.document_id == Document.id)
            .where(Document.collection_id.in_(collection_ids), DocumentPage.screenshot.is_not(None))
        )
        # The typed copies of tabular files (#431), and the single copy written before there were sheets.
        copy_keys = await self.db.scalars(
            select(DocumentTabularSheet.parquet_key)
            .join(Document, DocumentTabularSheet.document_id == Document.id)
            .where(Document.collection_id.in_(collection_ids), DocumentTabularSheet.parquet_key.is_not(None))
        )
        profiled = await self.db.execute(
            select(Document.collection_id, Document.id)
            .join(DocumentTabularProfile, DocumentTabularProfile.document_id == Document.id)
            .where(Document.collection_id.in_(collection_ids))
        )
        legacy = [legacy_tabular_copy_key(collection, document) for collection, document in profiled.all()]
        return [*storage_keys.all(), *screenshot_keys.all(), *copy_keys.all(), *legacy]

    async def delete(self, collection: Collection) -> None:
        await self.db.delete(collection)

    async def update_visibility(self, collection: Collection, visibility: CollectionVisibility) -> None:
        collection.visibility = visibility

    async def create_share(
        self,
        collection_id: uuid.UUID,
        subject_type: ShareSubjectType,
        identifier_hash: str,
        display_hint: str,
        permission: SharePermission = SharePermission.READ,
    ) -> CollectionShare:
        share = CollectionShare(
            collection_id=collection_id,
            subject_type=subject_type,
            permission=permission,
            status=ShareStatus.PENDING,
            invited_identifier_hash=identifier_hash,
            display_hint=display_hint,
        )
        self.db.add(share)
        await self.db.flush()
        return share

    async def create_active_group_share(
        self, collection_id: uuid.UUID, group_id: uuid.UUID, group_name: str, permission: SharePermission
    ) -> CollectionShare:
        """A share with one of the groups made in Muffin (#455): the group is a known object, not an identifier
        typed blind, so there is nothing to wait for and nothing to hash - and its name is what is shown."""
        share = CollectionShare(
            collection_id=collection_id,
            subject_type=ShareSubjectType.GROUP,
            status=ShareStatus.ACTIVE,
            permission=permission,
            subject_id=str(group_id),
            display_hint=group_name,
        )
        self.db.add(share)
        await self.db.flush()
        return share

    async def list_shares(self, collection_ids: Sequence[uuid.UUID]) -> Sequence[CollectionShare]:
        """Several ids so a collection's shares can be listed with its ancestors' in one query
        (inherited shares, #216)."""
        result = await self.db.execute(
            select(CollectionShare)
            .where(CollectionShare.collection_id.in_(collection_ids))
            .order_by(CollectionShare.created_at.desc())
        )
        return result.scalars().all()

    async def get_share(self, collection_id: uuid.UUID, share_id: uuid.UUID) -> CollectionShare | None:
        result = await self.db.execute(
            select(CollectionShare).where(
                CollectionShare.id == share_id, CollectionShare.collection_id == collection_id
            )
        )
        return result.scalar_one_or_none()

    async def delete_share(self, share: CollectionShare) -> None:
        await self.db.delete(share)

    async def resolve_pending_user_shares(self, email_hash: str, user_id: str) -> None:
        """Promotes every PENDING user-share invited under email_hash to ACTIVE, pointed at
        user_id - called once per login with the just-verified token's own email, never on
        anything an owner can trigger on demand (that's exactly the live-lookup this design
        avoids, see app/core/sharing.py)."""
        await self.db.execute(
            update(CollectionShare)
            .where(
                CollectionShare.subject_type == ShareSubjectType.USER,
                CollectionShare.status == ShareStatus.PENDING,
                CollectionShare.invited_identifier_hash == email_hash,
            )
            .values(status=ShareStatus.ACTIVE, subject_id=user_id, invited_identifier_hash=None)
        )

    async def resolve_pending_group_shares(self, group_hash: str, group_id: str) -> None:
        """Same as resolve_pending_user_shares, one call per group in the token's `groups`
        claim (see RequestContext.groups)."""
        await self.db.execute(
            update(CollectionShare)
            .where(
                CollectionShare.subject_type == ShareSubjectType.GROUP,
                CollectionShare.status == ShareStatus.PENDING,
                CollectionShare.invited_identifier_hash == group_hash,
            )
            .values(status=ShareStatus.ACTIVE, subject_id=group_id, invited_identifier_hash=None)
        )
