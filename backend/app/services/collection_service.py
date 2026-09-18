import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.sharing import hash_identifier, mask_email, mask_group, normalize_email, normalize_group
from app.models.collection import Collection, CollectionVisibility, ShareSubjectType
from app.repositories.collection_repository import CollectionRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.collection import (
    CollectionOut,
    CollectionSettingsUpdate,
    CollectionUpdate,
    EntityOut,
    QaPairOut,
    RelationOut,
    ShareCreate,
    ShareOut,
)
from app.schemas.pagination import Page, PaginationParams
from app.services import embedding_model_lookup, vector_store

# Last resort only, when the hub is unreachable/unconfigured and there's nothing else to go on -
# see create_collection, which otherwise resolves the admin-configured or hub-discovered model.
FALLBACK_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_COLLECTION_NAME = "Nouvelle collection"


class CollectionNotFoundError(Exception):
    pass


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
        self.qa_pairs = QaPairRepository(db)
        self.entities = EntityRepository(db)

    async def list_collections(self, user: RequestContext, pagination: PaginationParams) -> Page[CollectionOut]:
        collections, total = await self.repository.list_accessible(
            user.user_id, user.groups, limit=pagination.limit, offset=pagination.offset
        )
        return pagination.to_page(
            [CollectionOut.from_model(collection, user.user_id) for collection in collections], total
        )

    async def create_collection(self, user: RequestContext) -> CollectionOut:
        embedding_model = await embedding_model_lookup.default_embedding_model(self.db) or FALLBACK_EMBEDDING_MODEL
        collection = await self.repository.create(
            owner_id=user.user_id, name=DEFAULT_COLLECTION_NAME, embedding_model=embedding_model
        )
        await self.db.commit()
        return CollectionOut.from_model(collection, user.user_id)

    async def get_collection(self, collection_id: uuid.UUID, user: RequestContext) -> CollectionOut:
        collection = await self._get_accessible(collection_id, user)
        return CollectionOut.from_model(collection, user.user_id)

    async def update_collection(
        self, collection_id: uuid.UUID, user: RequestContext, update: CollectionUpdate
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        updated_by = _display_name(user)

        if update.name is not None and update.name.strip():
            await self.repository.update_name(collection, update.name.strip())
        if update.description is not None:
            await self.repository.update_description(collection, update.description, updated_by)
        if update.tags is not None:
            await self.repository.update_tags(collection, update.tags, updated_by)

        await self.db.commit()
        # tags/settings are already correct in memory (mutated directly above),
        # this is only to reload updated_at - onupdate=func.now() expires it
        # after the UPDATE, and accessing it later outside an active await
        # crashes with MissingGreenlet instead of lazy-loading like sync ORM would.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return CollectionOut.from_model(collection, user.user_id)

    async def update_settings(
        self, collection_id: uuid.UUID, user: RequestContext, update: CollectionSettingsUpdate
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)

        await self.repository.update_settings(
            collection,
            chunking_strategy=update.chunking_strategy,
            chunk_size=update.chunk_size,
            chunk_overlap=update.chunk_overlap,
            embedding_model=update.embedding_model,
            instructions=update.instructions.model_dump() if update.instructions is not None else None,
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
        return CollectionOut.from_model(collection, user.user_id)

    async def list_qa_pairs(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID | None = None
    ) -> list[QaPairOut]:
        await self._get_accessible(collection_id, user)
        pairs = await self.qa_pairs.list_by_collection(collection_id, document_id)
        return [
            QaPairOut(
                id=pair.id,
                question=pair.question,
                answer=pair.answer,
                source=pair.document.name if pair.document else None,
                origin=pair.origin,
                validated=pair.validated,
            )
            for pair in pairs
        ]

    async def list_entities(self, collection_id: uuid.UUID, user: RequestContext) -> list[EntityOut]:
        await self._get_accessible(collection_id, user)
        entities = await self.entities.list_by_collection(collection_id)
        return [
            EntityOut(id=entity.id, name=entity.name, type=entity.type, mentions=entity.mentions) for entity in entities
        ]

    async def list_relations(self, collection_id: uuid.UUID, user: RequestContext) -> list[RelationOut]:
        await self._get_accessible(collection_id, user)
        relations = await self.entities.list_relations_by_collection(collection_id)
        return [
            RelationOut(
                id=relation.id, from_entity=relation.from_entity.name, to=relation.to_entity.name, type=relation.type
            )
            for relation in relations
        ]

    async def delete_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        collection = await self._get_owned(collection_id, user)
        # Collected before the cascade delete removes the rows that reference
        # them - Postgres cleanup and RustFS cleanup can't be one transaction.
        rustfs_keys = await self.repository.list_rustfs_keys(collection_id)
        await self.repository.delete(collection)
        await self.db.commit()
        # Best-effort and after the commit: a RustFS/Qdrant failure here must
        # not roll back a deletion the user already sees as done.
        storage.delete_objects(rustfs_keys)
        vector_store.delete_collection(collection_id)

    async def update_visibility(
        self, collection_id: uuid.UUID, user: RequestContext, visibility: CollectionVisibility
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        await self.repository.update_visibility(collection, visibility)
        await self.db.commit()
        # Same reasoning as update_collection: onupdate=func.now() expires updated_at after the
        # UPDATE regardless of expire_on_commit, so it needs an explicit reload before use.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return CollectionOut.from_model(collection, user.user_id)

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
                collection_id, create.subject_type, hash_identifier(normalized), display_hint
            )
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()
            raise AlreadyInvitedError(str(collection_id)) from error
        return ShareOut.from_model(share)

    async def list_shares(self, collection_id: uuid.UUID, user: RequestContext) -> list[ShareOut]:
        await self._get_owned(collection_id, user)
        shares = await self.repository.list_shares(collection_id)
        return [ShareOut.from_model(share) for share in shares]

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
